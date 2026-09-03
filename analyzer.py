# -*- coding: utf-8 -*-
"""analyzer.py —— 笔记语义分析与智能复习提醒 (v1.0 · 零反斜杠实现 + 可选 LLM 语义增强)

设计说明: 本模块刻意不使用任何反斜杠字符(转义层级不可控),
正则一律用 显式字符区间([0-9]/[一-鿿]) 与 re.escape() 组装。

v1.0 语义增强(可选, 遵循「核心零依赖 + AI 可选」):
  有 DEEPSEEK_API_KEY 时, 概念提炼从「词频 top-N」升级为「LLM 提炼真核心概念」,
  并顺带生成一句话主题摘要(summary)。无 Key / 调用失败(熔断)时自动回退词频,
  行为与 v0.9 完全一致。熔断为进程级: 首次失败后本进程不再尝试, 防止批量扫描雪崩。

公开 API(与 v0.7 兼容):
  analyze_note(filepath)                    -> {"date","topic","concepts","tags","code_langs"[,"summary"]}
  update_analysis(learning_dir, dates=None) -> (data, added_dates)
  get_review_cards(learning_dir, today=None)
"""
import os
import re
import json
import urllib.request
from collections import Counter
from datetime import date

try:
    import jieba
    _HAS_JIEBA = True
except Exception:
    _HAS_JIEBA = False

_ANALYSIS_NAME = "analysis.json"
_STOPFILE_NAME = "stoplist.txt"
_CODE_LANGS = {"python", "js", "javascript", "ts", "typescript", "java", "go",
               "rust", "c", "cpp", "bash", "shell", "sql", "html", "css", "json", "yaml"}

# ---- v1.0 可选 LLM 语义增强 (遵循零反斜杠约定) ----
_LLM_DISABLED = False                                   # 进程级熔断: 首次失败后本进程不再尝试
_LLM_MAX_BODY = 3000                                    # 发往 LLM 的正文截断上限(字符)
_LLM_TIMEOUT = 15                                       # 单次调用超时(秒)
_LLM_API = "https://api.deepseek.com/chat/completions"
_LLM_MODEL = "deepseek-chat"

BT = chr(96)                                          # 反引号
FENCE = BT * 3
WS_CLASS = "[" + chr(32) + chr(9) + "]"
MD_DATE_RE = re.compile("^([0-9]{4}-[0-9]{2}-[0-9]{2})[.]md$")
_FENCE_RE = re.compile("^" + re.escape(FENCE) + "([A-Za-z0-9_]+)", re.M)
_NOISY_TOKEN = re.compile("^[^0-9A-Za-z一-鿿]+$")       # 纯符号(无字母数字汉字)
_BAD_WORDS = set(["我们", "你们", "他们", "自己", "什么", "没有", "还是", "如果", "因为",
                  "所以", "然后", "开始", "完成", "学习", "今天", "明天", "昨天", "内容", "问题",
                  "进行", "使用", "实现", "可以", "这个", "那个", "一下", "应该", "需要",
                  "现在", "时候", "知道", "觉得", "非常"])

def _load_stopset(learning_dir):
    """内置停用集 并集 stoplist.txt(用户可扩充); 文件不存在则自动创建初始版"""
    base = set(_BAD_WORDS)
    for ch in "的了和是有在不人都一个这那它她我你吧吗呢啊呀哦嗯很太也都被把让向往从到于对会能可要想着看听读写做用过等就还说而或与其此每各某":
        base.add(ch)
    p = os.path.join(learning_dir, _STOPFILE_NAME)
    if not os.path.exists(p):
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("# learning 停用词表(每行一个词条; 井号开头为注释; 可自行扩充, 刷新即生效)" + chr(10))
                f.write(FENCE + chr(10) + "---" + chr(10) + "***" + chr(10) + "# ---- 中文虚词 ----" + chr(10))
        except Exception:
            pass
    else:
        try:
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    w = ln.strip()
                    if not w or w.startswith("#"):
                        continue
                    base.add(w.lower())
        except Exception:
            pass
    return base


def _strip_md_line(ln):
    """单行 markdown 洗刷: 去标题井号/引用符/列表符/粗斜体标记"""
    out = ln.lstrip("# ").lstrip("> ")
    out = out.lstrip("-").lstrip("*").lstrip("+")
    out = out.replace("**", "").replace("__", "")
    return out


def _strip_markdown(text):
    """分词前清洗: 围栏行删除、行内代码替换为占位、链接图片只留文字、tags 行删除"""
    kept = []
    in_fence = False
    for ln in text.splitlines():
        if ln.startswith(FENCE):
            in_fence = not in_fence                     # 围栏内容整体丢弃
            continue
        if in_fence:
            continue
        kept.append(_strip_md_line(ln))
    body = chr(10).join(kept)
    body = re.sub("!" + re.escape("[") + "[^" + chr(93) + "]*" + re.escape("](") + "[^" + chr(41) + "]*" + re.escape(")"), "", body)
    body = re.sub(re.escape("[") + "([^" + chr(93) + "]*)" + re.escape("](") + "[^" + chr(41) + "]*" + re.escape(")"), r"LINKTXT", body)
    body = re.sub("tags" + WS_CLASS + "*:" + WS_CLASS + "*.*", "", body, flags=re.I)
    return body


def _tokenize(text):
    if _HAS_JIEBA:
        return [w.strip() for w in jieba.cut(text) if w.strip()]
    return re.findall(r"[一-鿿]{2,4}|[A-Za-z]{2,}", text)


def _call_deepseek(prompt, key):
    """调用 DeepSeek chat 接口, 返回 assistant 文本; 任何异常向上抛(由调用方熔断降级)"""
    payload = json.dumps({
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是严谨的学习内容语义分析师, 只基于给定笔记提炼概念, 禁止编造任何笔记之外的内容。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        _LLM_API, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _extract_json(text):
    """从模型输出中提取最外层 JSON 对象(容错 markdown 围栏/前后缀); 失败返回 None"""
    a = str(text or "").find("{")
    b = str(text or "").rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(str(text)[a:b + 1])
    except Exception:
        return None


def _llm_concepts(body, topic, key):
    """LLM 提炼核心概念(3~5 个)与一句话摘要; 解析失败返回 None(调用方回退词频)"""
    snippet = (body or "")[:_LLM_MAX_BODY]
    prompt = ("请阅读以下学习笔记, 提炼真正核心的概念(3 到 5 个, 每个 2 到 20 字, "
              + "中文优先、英文术语可保留), 以及一句话主题摘要(不超过 30 字)。" + chr(10)
              + "要求: 只基于笔记内容, 禁止编造; concepts 是概念或知识点, 不是高频词或形容词。"
              + chr(10)
              + '输出纯 JSON: {"concepts": [...], "summary": "..."}, 不要多余文字。'
              + chr(10) + "笔记主题: " + (topic or "")
              + chr(10) + "笔记正文:" + chr(10) + snippet)
    text = _call_deepseek(prompt, key)
    obj = _extract_json(text)
    if not isinstance(obj, dict):
        return None
    raw = obj.get("concepts")
    if not isinstance(raw, list):
        return None
    cleaned = []
    for c in raw:
        s = str(c).strip()
        if 2 <= len(s) <= 40 and s not in _BAD_WORDS:
            cleaned.append(s)
        if len(cleaned) >= 5:
            break
    if not cleaned:
        return None
    summary = str(obj.get("summary") or "").strip()[:_LLM_MAX_BODY]
    return {"concepts": cleaned, "summary": summary[:60]}


def analyze_note(filepath, learning_dir=None):
    global _LLM_DISABLED
    ld = learning_dir or os.path.dirname(os.path.dirname(os.path.abspath(filepath)))
    stopset = _load_stopset(ld)
    with open(filepath, encoding="utf-8") as f:
        raw = f.read()
    dm = MD_DATE_RE.match(os.path.basename(filepath))
    date_str = dm.group(1) if dm else ""
    lines = raw.splitlines()
    topic = date_str
    for ln in lines:
        if ln.startswith("#"):
            topic = ln.lstrip("# ").strip() or date_str
            break
    tags = []
    for ln in lines[1:4]:
        tm = re.match("tags" + WS_CLASS + "*:" + WS_CLASS + "*(.+)", ln.strip(), re.I)
        if tm:
            tags = [t.strip() for t in tm.group(1).split(",") if t.strip()]
            break
    langs = set()
    for m in _FENCE_RE.finditer(raw):
        lang = m.group(1).lower()
        if lang in _CODE_LANGS:
            langs.add(lang)
    body = _strip_markdown(chr(10).join(ln for ln in lines if not ln.startswith(FENCE)))
    words = [w.lower() for w in _tokenize(body)]

    def noisy(w):
        if len(w) < 2:
            return True                                 # 单字符
        if w.isdigit():
            return True                                  # 纯数字
        if w in stopset or w in _BAD_WORDS:
            return True
        if _NOISY_TOKEN.match(w):
            return True                                  # 纯符号(## --- *** 等)
        return False

    words = [w for w in words if not noisy(w)]
    concepts = [w for w, _ in Counter(words).most_common(5)]
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key and not _LLM_DISABLED:
        try:
            llm = _llm_concepts(body, topic, key)
        except Exception:
            llm = None
        if llm:
            rec = {"date": date_str, "topic": topic,
                   "concepts": llm["concepts"],
                   "tags": tags, "code_langs": sorted(langs)}
            if llm["summary"]:
                rec["summary"] = llm["summary"]
            return rec
        _LLM_DISABLED = True                             # 熔断: 本进程不再尝试, 防批量雪崩
    return {"date": date_str, "topic": topic, "concepts": concepts,
            "tags": tags, "code_langs": sorted(langs)}


def _analysis_path(learning_dir):
    return os.path.join(learning_dir, "daily", _ANALYSIS_NAME)


def load_analysis(learning_dir):
    p = _analysis_path(learning_dir)
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    return {"notes": {}}


def save_analysis(learning_dir, data):
    with open(_analysis_path(learning_dir), "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_analysis(learning_dir, dates=None):
    daily_dir = os.path.join(learning_dir, "daily")
    data = load_analysis(learning_dir)
    notes = data.setdefault("notes", {})
    targets = []
    if dates is None:
        if os.path.isdir(daily_dir):
            for fn in os.listdir(daily_dir):
                dm = MD_DATE_RE.match(fn)
                if dm and dm.group(1) not in notes:
                    targets.append(os.path.join(daily_dir, fn))
    else:
        for ds in dates:
            p = os.path.join(daily_dir, ds + ".md")
            if os.path.exists(p):
                targets.append(p)
    added = []
    for p in sorted(targets):
        try:
            rec = analyze_note(p, learning_dir=learning_dir)
        except Exception:
            continue
        notes[rec["date"]] = {"topic": rec["topic"], "concepts": rec["concepts"],
                              "tags": rec["tags"], "code_langs": rec["code_langs"]}
        added.append(rec["date"])
    if added:
        save_analysis(learning_dir, data)
    return data, added


def get_review_cards(learning_dir, today=None):
    today = today or date.today()
    notes = load_analysis(learning_dir).get("notes", {})
    appear = {}
    for ds in sorted(notes.keys()):
        for c in notes[ds].get("concepts", []):
            appear.setdefault(c, [])
            if ds not in appear[c]:
                appear[c].append(ds)
    cards = []
    for c, dss in appear.items():
        first = date.fromisoformat(dss[0])
        last = date.fromisoformat(dss[-1])
        gap_last = (today - last).days
        age_first = (today - first).days
        if len(dss) >= 2 and age_first >= 7:
            status = "已巩固"
        elif gap_last >= 3:
            status = "需复习"
        elif gap_last <= 1:
            status = "新学"
        else:
            status = "巩固中"
        cards.append({"concept": c, "status": status, "source_date": dss[-1],
                      "source_file": dss[-1] + ".md", "count": len(dss)})
    cards.sort(key=lambda x: (x["status"] != "需复习", x["source_date"]))
    return cards


# ---- v1.1 Phase B 语义纵深(可选 LLM, 复用 _call_deepseek + 熔断基建) ----
# 铁律: 零反斜杠(换行一律 chr(10)); 无 Key / 熔断时完整回退, 零二次调用。


def llm_weekly_insight(summary_payload, key=None):
    """基于本周真实聚合(概念摘要/复习趋势/掌握分)生成「本周洞察」(薄弱概念、趋势点评, <=150 字)。

    复用 analyzer 的 _call_deepseek + _LLM_DISABLED 熔断基建, 与 services.weekly_report 共用一套降级策略,
    避免各模块自建 DeepSeek 调用(2026-09-03 用户盯防项)。

    返回: 洞察文本(str, 已截断到 150 字) 或 None(无 Key / 熔断 / 调用失败 / 解析失败)。
    调用失败时置位 _LLM_DISABLED, 本进程后续零调用。
    """
    global _LLM_DISABLED
    key = key if key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
    if not key or _LLM_DISABLED:
        return None
    prompt = ("你是严谨的学习复盘助手。基于给定的本周真实数据, 用一句话点出" + chr(10)
              + "1) 最该优先补的概念(1 到 2 个, 给理由)" + chr(10)
              + "2) 本周趋势点评(完成率/复习表现)" + chr(10)
              + "要求: 只基于给定数据, 禁止编造; 中文; 不超过 150 字; 不要分点符号以外的多余内容。"
              + chr(10) + '输出纯 JSON: {"insight": "..."}, 不要多余文字。' + chr(10)
              + "真实数据:" + chr(10)
              + json.dumps(summary_payload, ensure_ascii=False)[:_LLM_MAX_BODY])
    try:
        text = _call_deepseek(prompt, key)
        obj = _extract_json(text)
        if not isinstance(obj, dict):
            _LLM_DISABLED = True
            return None
        insight = str(obj.get("insight") or "").strip()
        if not insight:
            _LLM_DISABLED = True
            return None
        return insight[:150]
    except Exception:
        _LLM_DISABLED = True                                 # 熔断: 后续零二次调用
        return None


def llm_concept_relations(pairs, key=None, batch_limit=10):
    """判定概念对的语义关系(上位 / 下位 / 相关 / 前置), 用于把知识图谱从「共现」升级为「语义结构」。

    pairs: [{"a": ..., "b": ...}, ...]; 每批最多 batch_limit 对(默认 10), 超出部分本批不处理(调用方分批)。
    复用 _call_deepseek + 熔断; 无 Key / 熔断 / 失败 -> 返回 None(调用方回退共现), 零二次调用。
    返回: {"rels": [{"a":..., "b":..., "type":...}, ...]} 或 None。
    """
    global _LLM_DISABLED
    key = key if key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
    if not key or _LLM_DISABLED or not pairs:
        return None
    batch = [p for p in pairs if p.get("a") and p.get("b")][:batch_limit]
    if not batch:
        return None
    prompt = ("你是知识结构分析师。判定下列概念对之间的语义关系, 每对只能选一种类型:" + chr(10)
              + "上位(a 是 b 的上位概念) / 下位(a 是 b 的下位概念) / 相关(同层关联) / 前置(学 a 是学 b 的前提)。"
              + chr(10) + "要求: 只基于常识与给定概念名, 禁止编造额外概念; 无法判定时填 相关。" + chr(10)
              + '输出纯 JSON: {"rels": [{"a": "...", "b": "...", "type": "..."}]}, 不要多余文字。' + chr(10)
              + "概念对:" + chr(10) + json.dumps(batch, ensure_ascii=False)[:_LLM_MAX_BODY])
    try:
        text = _call_deepseek(prompt, key)
        obj = _extract_json(text)
        if not isinstance(obj, dict) or not isinstance(obj.get("rels"), list):
            _LLM_DISABLED = True
            return None
        ok_types = ("上位", "下位", "相关", "前置")
        rels = []
        for r in obj["rels"]:
            if not isinstance(r, dict):
                continue
            t = str(r.get("type") or "").strip()
            if t not in ok_types:
                t = "相关"
            rels.append({"a": str(r.get("a") or "").strip().lower(),
                         "b": str(r.get("b") or "").strip().lower(),
                         "type": t})
        if not rels:
            _LLM_DISABLED = True
            return None
        return {"rels": rels}
    except Exception:
        _LLM_DISABLED = True
        return None
