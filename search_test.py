# -*- coding: utf-8 -*-
"""search_test.py —— 全文搜索引擎单元测试 (v1.3 · 纯标准库)
跑法A: pytest search_test.py      跑法B: python search_test.py (零依赖runner)
覆盖: 中英混合分词(CJK二元组/小写化) / 四类文档建索引(任务/笔记/知识点/标签) /
      持久化与mtime新鲜度复用(force与过期重建) / 相关度(标题加权)排序 /
      CJK子串查询与单字回退扫描 / 高亮片段HTML转义 / 增量更新单篇笔记 /
      limit与type过滤。全部临时目录+固定内容。
"""
import datetime
import json
import os
import shutil
import tempfile
import time

import search


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _mk_dir():
    """标准四源目录: 1任务 + 1笔记(含tags行与正文) + 记忆档案1概念"""
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "tasks.json"), json.dumps({
        "version": 3, "log": [],
        "days": {"2099-07-10": [
            {"id": "t1", "text": "写学习周报并整理错题", "done": False,
             "carried": False, "src_date": "2099-07-10", "priority": 2}]},
        "history": []}, ensure_ascii=False), )
    _write(os.path.join(d, "daily", "2099-07-10.md"),
           "# 遗忘曲线引擎调研\n"
           "tags: mcp, 遗忘曲线\n"
           "今天研究了遗忘曲线引擎的复习间隔，涉及艾宾浩斯与SM-2。\n"
           "<script>alert(1)</script>\n")
    _write(os.path.join(d, "daily", "knowledge.json"), json.dumps({
        "version": 1,
        "knowledge": {"遗忘曲线": {"first_seen": "2099-07-10",
                                   "source_date": "2099-07-10",
                                   "last_review_ts": None,
                                   "review_count": 0, "ease_factor": 2.5}}},
        ensure_ascii=False))
    return d


# ---------------- 分词 ----------------
def test_tokenize_cjk_bigrams_and_latin_lower():
    toks = search.tokenize("函数调用 Ctrl")
    assert "函数" in toks and "数调" in toks and "调用" in toks, toks
    assert "ctrl" in toks and "Ctrl" not in toks, toks


def test_tokenize_single_cjk_char_kept_for_fallback():
    assert search.tokenize("忘") == ["忘"]
    assert search.tokenize("") == []
    assert "sm" in search.tokenize("SM-2") and "2" in search.tokenize("SM-2")


# ---------------- 建索引与持久化 ----------------
def test_build_index_covers_four_sources():
    d = _mk_dir()
    try:
        idx = search.build_index(d)
        types = {doc["type"] for doc in idx["docs"].values()}
        assert {"task", "note", "concept", "tag"} <= types, types
        assert any(doc["title"] == "写学习周报并整理错题"
                   for doc in idx["docs"].values() if doc["type"] == "task")
        note = next(doc for doc in idx["docs"].values() if doc["type"] == "note")
        assert note["url"] == "/editor?date=2099-07-10"
        assert "艾宾浩斯" in note["text"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_index_persisted_and_reused_when_fresh():
    d = _mk_dir()
    try:
        idx1 = search.build_index(d)
        assert idx1["_stats"]["reused"] is False
        p = os.path.join(d, "search_index.json")
        assert os.path.exists(p), "索引必须落盘 search_index.json"
        time.sleep(0.01)
        idx2 = search.build_index(d)
        assert idx2["_stats"]["reused"] is True, "源未变化必须复用缓存"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_force_and_stale_both_rebuild():
    d = _mk_dir()
    try:
        search.build_index(d)
        assert search.build_index(d, force=True)["_stats"]["reused"] is False
        time.sleep(0.01)
        note_p = os.path.join(d, "daily", "2099-07-10.md")
        os.utime(note_p, (time.time() + 5, time.time() + 5))    # 源文件变新
        assert search.build_index(d)["_stats"]["reused"] is False, "源过期必须重建"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 搜索与排序 ----------------
def test_search_finds_task_title_with_highlight():
    d = _mk_dir()
    try:
        search.build_index(d)
        hits = search.search(d, "周报")
        assert hits and hits[0]["type"] == "task", hits
        assert "<mark>" in hits[0]["snippet"], hits[0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_search_finds_note_body_and_cjk_substring():
    d = _mk_dir()
    try:
        search.build_index(d)
        hits = search.search(d, "曲线引擎")                     # 跨词子串
        assert any(x["type"] == "note" for x in hits), hits
        hits2 = search.search(d, "艾宾浩斯")
        assert any(x["type"] == "note" for x in hits2), hits2
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_search_finds_concept_and_tag():
    d = _mk_dir()
    try:
        search.build_index(d)
        assert any(x["type"] == "concept" for x in search.search(d, "遗忘曲线"))
        assert any(x["type"] == "tag" for x in search.search(d, "mcp"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_title_match_outranks_body_only():
    d = _mk_dir()
    _write(os.path.join(d, "daily", "2099-07-11.md"),
           "# 随手记\n\n正文里提到了周报两个字但标题无关。\n")
    try:
        search.build_index(d)
        hits = search.search(d, "周报")
        assert hits[0]["type"] == "task", hits                   # 标题命中 > 正文命中
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_single_char_query_fallback_scan():
    d = _mk_dir()
    try:
        search.build_index(d)
        hits = search.search(d, "忘")                            # 单字不在二元组词表
        assert any("遗忘" in x["title"] or "遗忘" in x["snippet"] for x in hits), hits
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_snippet_escapes_html_before_highlight():
    d = _mk_dir()
    try:
        search.build_index(d)
        hits = search.search(d, "alert")
        assert hits, "正文里的 script 内容应可被搜到(笔记全文索引)"
        sn = hits[0]["snippet"]
        assert "<script>" not in sn and "&lt;script&gt;" in sn, sn
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_limit_and_type_filter():
    d = _mk_dir()
    _write(os.path.join(d, "daily", "2099-07-11.md"),
           "# mcp 笔记二\ntags: mcp\nmcp 内容补充\n")
    try:
        search.build_index(d)
        hits = search.search(d, "mcp", limit=2)
        assert len(hits) <= 2
        only_note = search.search(d, "mcp", types=["note"])
        assert all(x["type"] == "note" for x in only_note) and only_note
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 增量更新 ----------------
def test_incremental_note_update_without_full_rebuild():
    d = _mk_dir()
    try:
        search.build_index(d)
        new_text = ("# 遗忘曲线引擎调研\n"
                    "tags: mcp, 遗忘曲线\n"
                    "补充：量子速读法并不存在。\n")
        _write(os.path.join(d, "daily", "2099-07-10.md"), new_text)
        search.update_note(d, "2099-07-10")                      # 只重索引这一篇
        hits = search.search(d, "量子速读")
        assert hits and hits[0]["type"] == "note", hits          # 新词立即可搜
        p = os.path.join(d, "search_index.json")
        saved = json.load(open(p, encoding="utf-8-sig"))
        assert saved["docs"]["note:2099-07-10"]["text"].startswith("# 遗忘曲线")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_search_empty_query_returns_empty():
    d = _mk_dir()
    try:
        search.build_index(d)
        assert search.search(d, "") == []
        assert search.search(d, "   ") == []
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
