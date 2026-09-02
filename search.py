# -*- coding: utf-8 -*-
r"""search.py —— 全文搜索引擎 (v1.3 · 纯标准库倒排索引)

覆盖四类文档(v1.3 规格: 任务标题 / 笔记正文 / 知识点名称 / 标签):
  task:<日期>:<任务id>   title=任务文本      url=/
  note:<日期>            title=首行标题      url=/editor?date=<日期>   text=全文
  concept:<概念名>       title=概念名        url=/editor?date=source_date
  tag:<标签名>           title=标签名        url=/

分词: CJK 连续段切**重叠二元组**(子串查询天然命中), 单字成词供回退扫描;
     拉丁字母数字下划线整词小写。查询与索引同器, 保证口径一致。
持久化: search_index.json = {version, built_ts, src_mtimes, docs{id→doc}, index{token→[id]}}
新鲜度: 记录每个源文件 mtime; 全部未变 → 直接复用缓存(零重扫);
       force=True 或任一源变新 → 全量重建。笔记保存走 update_note() 增量更新单篇+标签文档。
相关度: Σ 词频×IDF + 标题命中加成(×3) + 类型微调; 稳定排序并列按 id。

公开 API:
  tokenize(text) -> [token]
  build_index(learning_dir, force=False) -> index(含 _stats.reused/docs)
  update_note(learning_dir, date) -> None        # 笔记保存后调用
  search(learning_dir, query, limit=20, types=None)
      -> [{id,type,title,snippet,url,score}]     # snippet 已转义并 <mark> 高亮
"""
import os
import re
import json
import math
import datetime

INDEX_NAME = "search_index.json"
_CJK_RUN = re.compile("[一-鿿]+")
_LATIN = re.compile("[A-Za-z0-9_]+")
_DATE_MD = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_TAGS_LINE = re.compile(r"^tags\s*:\s*(.+)$", re.I)
_TYPE_BOOST = {"task": 1.2, "concept": 1.1, "tag": 1.05, "note": 1.0}
TITLE_BONUS = 3.0


# ---------------- 分词 ----------------
def tokenize(text):
    """CJK 重叠二元组(+单字回退词) 与 拉丁小写整词"""
    text = str(text or "")
    out = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            out.append(run)
        else:
            for i in range(len(run) - 1):
                out.append(run[i:i + 2])
    for w in _LATIN.findall(text):
        out.append(w.lower())
    return out


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------- 文档采集 ----------------
def _collect_tasks(d):
    st = {}
    p = os.path.join(d, "tasks.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                st = json.load(f)
        except Exception:
            st = {}
    docs = {}
    for date, bucket in (st.get("days") or {}).items():
        for t in bucket or []:
            if not isinstance(t, dict) or not t.get("text"):
                continue
            did = "task:%s:%s" % (date, t.get("id"))
            docs[did] = {"id": did, "type": "task", "title": t["text"],
                         "date": date, "url": "/", "text": t["text"]}
    return docs


def _parse_note(raw_text):
    """返回 (title, tags列表)——正文就是全文本身"""
    lines = raw_text.splitlines()
    title = ""
    tags = []
    for ln in lines[:6]:
        tm = _TAGS_LINE.match(ln.strip())
        if tm:
            tags = [x.strip() for x in tm.group(1).split(",") if x.strip()]
            continue
        if ln.startswith("#") and not title:
            title = ln.lstrip("# ").strip()
    return (title or ""), tags


def _collect_notes(d):
    docs = {}
    tags_docs = {}
    daily = os.path.join(d, "daily")
    mtime_map = {}
    if os.path.isdir(daily):
        for fn in sorted(os.listdir(daily)):
            m = _DATE_MD.match(fn)
            if not m:
                continue
            ds = m.group(1)
            p = os.path.join(daily, fn)
            try:
                with open(p, encoding="utf-8-sig") as f:
                    raw = f.read()
                mtime_map["daily/" + fn] = os.path.getmtime(p)
            except OSError:
                continue
            title, tags = _parse_note(raw)
            docs["note:" + ds] = {"id": "note:" + ds, "type": "note",
                                  "title": title or ds, "date": ds,
                                  "url": "/editor?date=" + ds, "text": raw}
            for tg in tags:
                td = "tag:" + tg
                if td not in tags_docs:
                    tags_docs[td] = {"id": td, "type": "tag", "title": tg,
                                     "date": "", "url": "/", "text": tg}
    return docs, tags_docs, mtime_map


def _collect_concepts(d):
    docs = {}
    p = os.path.join(d, "daily", "knowledge.json")
    data = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            data = {}
    for name, rec in (data.get("knowledge") or {}).items():
        did = "concept:" + name
        docs[did] = {"id": did, "type": "concept", "title": name,
                     "date": rec.get("source_date", ""),
                     "url": "/editor?date=" + rec.get("source_date", ""),
                     "text": name}
    return docs


# ---------------- 构建与复用 ----------------
def _index_path(learning_dir):
    return os.path.join(learning_dir, INDEX_NAME)


def _current_mtimes(learning_dir):
    mt = {}
    tp = os.path.join(learning_dir, "tasks.json")
    if os.path.exists(tp):
        mt["tasks.json"] = os.path.getmtime(tp)
    kp = os.path.join(learning_dir, "daily", "knowledge.json")
    if os.path.exists(kp):
        mt["daily/knowledge.json"] = os.path.getmtime(kp)
    daily = os.path.join(learning_dir, "daily")
    if os.path.isdir(daily):
        for fn in os.listdir(daily):
            if _DATE_MD.match(fn):
                p = os.path.join(daily, fn)
                mt["daily/" + fn] = os.path.getmtime(p)
    return mt


def _assemble(docs):
    """docs -> 完整索引结构(倒排表 token → 有序 id 列表)"""
    inv = {}
    for did, doc in docs.items():
        toks = set(tokenize(doc["title"]) + tokenize(doc["text"]))
        for tk in toks:
            inv.setdefault(tk, []).append(did)
    for tk in inv:
        inv[tk].sort()
    return {"version": 1,
            "built_ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "src_mtimes": {},
            "_stats": {"reused": False, "docs": len(docs)},
            "docs": docs, "index": inv}


def build_index(learning_dir, force=False):
    """构建(或复用)全量索引。源 mtime 全部未变且非 force 时直接读缓存。"""
    saved = None
    p = _index_path(learning_dir)
    cur_mt = _current_mtimes(learning_dir)
    if not force and os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                saved = json.load(f)
        except Exception:
            saved = None
        if (isinstance(saved, dict) and saved.get("docs") is not None
                and saved.get("src_mtimes") == cur_mt
                and saved.get("index")):
            saved["_stats"] = {"reused": True,
                               "docs": len(saved["docs"])}
            return saved
    tasks_docs = _collect_tasks(learning_dir)
    note_docs, tag_docs, note_mt = _collect_notes(learning_dir)
    concept_docs = _collect_concepts(learning_dir)
    docs = {}
    docs.update(tasks_docs)
    docs.update(note_docs)
    docs.update(tag_docs)
    docs.update(concept_docs)
    idx = _assemble(docs)
    idx["src_mtimes"] = cur_mt
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8-sig") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(tmp, p)                                   # 原子落盘(同 settings 手法)
    except OSError:
        pass                                                 # 只读盘等场景放弃缓存不致命
    return idx


def _doc_tokens(doc):
    """计算文档的 token 集合(增量更新时用于 diff)。"""
    return set(tokenize(doc["title"]) + tokenize(doc["text"]))


def _remove_doc_from_index(inv, did, old_tokens):
    """从倒排表中移除指定文档的旧 token 条目。"""
    for tk in old_tokens:
        ids = inv.get(tk)
        if ids is None:
            continue
        new_ids = [i for i in ids if i != did]
        if new_ids:
            inv[tk] = new_ids
        else:
            del inv[tk]


def _add_doc_to_index(inv, did, new_tokens):
    """向倒排表添加指定文档的新 token 条目(保持有序)。"""
    for tk in new_tokens:
        ids = inv.setdefault(tk, [])
        if did not in ids:
            ids.append(did)
            ids.sort()


def update_note(learning_dir, date):
    """笔记保存后的增量更新: 仅重采这一篇的 note 文档 + 局部更新倒排表。
    标签文档也增量处理(仅添加新标签, 不重扫全部笔记)。
    性能: 从 O(全量文档 × 全量分词) 降至 O(单篇分词 + 倒排局部更新)。"""
    idx_path = _index_path(learning_dir)
    idx = build_index(learning_dir)  # 先保证有最新基座(通常命中缓存)
    docs = idx["docs"]
    inv = idx["index"]

    old_id = "note:" + date
    old_tokens = _doc_tokens(docs[old_id]) if old_id in docs else set()

    # --- 重采本篇 ---
    p = os.path.join(learning_dir, "daily", date + ".md")
    raw = ""
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                raw = f.read()
        except OSError:
            raw = ""

    if raw:
        title, _tags = _parse_note(raw)
        new_doc = {"id": old_id, "type": "note",
                   "title": title or date, "date": date,
                   "url": "/editor?date=" + date, "text": raw}
        new_tokens = _doc_tokens(new_doc)
        docs[old_id] = new_doc
    else:
        # 文件被删除: 从索引中移除
        new_tokens = set()
        if old_id in docs:
            docs.pop(old_id)

    # --- 局部更新倒排表(增量 diff) ---
    if old_tokens or new_tokens:
        removed = old_tokens - new_tokens
        added = new_tokens - old_tokens
        if removed:
            _remove_doc_from_index(inv, old_id, removed)
        if added:
            _add_doc_to_index(inv, old_id, added)

    # --- 标签文档增量更新(仅添加新标签, 不重扫全部笔记) ---
    if raw:
        _, _tags = _parse_note(raw)
        for tg in _tags:
            td = "tag:" + tg
            if td not in docs:
                docs[td] = {"id": td, "type": "tag", "title": tg,
                            "date": "", "url": "/", "text": tg}
                _add_doc_to_index(inv, td, _doc_tokens(docs[td]))

    # --- 原子落盘 ---
    idx["_stats"] = {"reused": False, "docs": len(docs)}
    idx["src_mtimes"] = _current_mtimes(learning_dir)
    try:
        tmp = idx_path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(tmp, idx_path)
    except OSError:
        pass
    return idx


# ---------------- 检索 ----------------
def _idf(total_docs, df):
    return math.log(1.0 + total_docs / float(df or 1))


def search(learning_dir, query, limit=20, types=None):
    """检索: 相关度 = Σ tf×IDF ×类型微调 (+标题命中×TITLE_BONUS);
    单字 CJK 走线性回退扫描。snippet 已 HTML 转义并对命中词打 <mark>。"""
    q_terms = []
    seen = set()
    for tk in tokenize(query):
        if tk not in seen:
            seen.add(tk)
            q_terms.append(tk)
    if not q_terms:
        return []
    idx = build_index(learning_dir)
    docs = idx["docs"]
    inv = idx["index"]
    total = max(1, len(docs))
    scores = {}
    single_cjk = [t for t in q_terms if len(t) == 1 and _CJK_RUN.fullmatch(t)]
    for term in q_terms:
        if len(term) == 1 and _CJK_RUN.fullmatch(term):
            continue                                        # 单字稍后统一回退扫
        hit_ids = inv.get(term)
        if not hit_ids:
            continue
        idf = _idf(total, len(hit_ids))
        for did in hit_ids:
            doc = docs.get(did)
            if not doc:
                continue
            tf = (doc["text"].lower().count(term)
                  + doc["title"].lower().count(term) * TITLE_BONUS)
            scores[did] = scores.get(did, 0.0) + tf * idf
    if single_cjk:                                          # 回退: 全文含字即候选
        for did, doc in docs.items():
            low = (doc["title"] + "\n" + doc["text"]).lower()
            if all(ch in low for ch in single_cjk):
                scores[did] = scores.get(did, 0.0) + 0.5 * len(single_cjk)
    if types:
        types = set(types)
        scores = {k: v for k, v in scores.items()
                  if docs.get(k, {}).get("type") in types}

    def type_of(k):
        return docs.get(k, {}).get("type", "")

    ranked = sorted(scores.items(),
                    key=lambda kv: (-kv[1], -_TYPE_BOOST.get(type_of(kv[0]), 1.0), kv[0]))
    results = []
    for did, sc in ranked[:max(0, int(limit))]:
        doc = docs.get(did)
        if not doc:
            continue
        results.append({"id": did, "type": doc["type"], "title": doc["title"],
                        "url": doc["url"], "score": round(sc, 4),
                        "snippet": _snippet(doc["text"], doc["title"], q_terms)})
    return results


def _snippet(text, title, terms, window=40):
    """取首个命中的上下文窗口, HTML 转义后对原始命中串打 <mark>"""
    hay = str(text or "")
    lower = hay.lower()
    pos = -1
    hit_term = ""
    for term in terms:
        p = lower.find(term.lower())
        if p >= 0 and (pos < 0 or p < pos):
            pos, hit_term = p, hay[p:p + len(term)]
    base = title or ""
    if pos < 0:
        snip = hay[:window * 2]
    else:
        a = max(0, pos - window // 2)
        snip = ("…" if a > 0 else "") + hay[a:a + window * 2] + \
               ("…" if a + window * 2 < len(hay) else "")
    esc = _esc(snip)
    if hit_term:
        pattern = re.escape(_esc(hit_term)).replace(r"\ ", r"\s+")
        esc = re.sub("(" + pattern + ")", r"<mark>\1</mark>", esc,
                     flags=re.IGNORECASE)
    return esc
