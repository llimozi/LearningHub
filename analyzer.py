# -*- coding: utf-8 -*-
"""analyzer.py —— 笔记语义分析与智能复习提醒 (v0.9 · 零反斜杠实现)

设计说明: 本模块刻意不使用任何反斜杠字符(转义层级不可控),
正则一律用 显式字符区间([0-9]/[一-鿿]) 与 re.escape() 组装。

公开 API(与 v0.7 兼容):
  analyze_note(filepath)                    -> {"date","topic","concepts","tags","code_langs"}
  update_analysis(learning_dir, dates=None) -> (data, added_dates)
  get_review_cards(learning_dir, today=None)
"""
import os
import re
import json
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


def analyze_note(filepath, learning_dir=None):
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
