# -*- coding: utf-8 -*-
"""forgetting_test.py —— 遗忘曲线引擎单元测试 (v1.1 · 纯标准库)
跑法A: pytest forgetting_test.py     跑法B: python forgetting_test.py (零依赖runner)
覆盖: 从台账同步知识点档案(幂等/source_date推进/旧档不回退) /
      艾宾浩斯间隔表 1-2-4-7-15-30 与 ease 缩放 / 打分复习与 ease 钳制 /
      到期队列排序(越危险越靠前) / 记忆衰减百分比单调性。全部临时目录+固定日期。
"""
import datetime
import json
import os
import shutil
import tempfile

from forgetting import (INTERVALS, load_knowledge, save_knowledge,
                        sync_from_analysis, interval_days, due_cards,
                        mark_reviewed, retention_percent, decay_rows)

TODAY = datetime.date(2099, 7, 10)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _dir_with_notes(notes):
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "daily", "analysis.json"), {"notes": notes})
    return d


def _note(topic, concepts, tags=None):
    return {"topic": topic, "concepts": concepts, "tags": tags or [], "code_langs": []}


# ---------------- 同步 ----------------
def test_sync_creates_records_with_first_and_last_seen():
    d = _dir_with_notes({
        "2099-07-01": _note("A", ["mcp", "rag"]),
        "2099-07-05": _note("B", ["mcp"]),
    })
    try:
        data, added = sync_from_analysis(d, today=TODAY)
        kn = data["knowledge"]
        assert added == 2 and set(kn) == {"mcp", "rag"}, kn
        assert kn["mcp"]["first_seen"] == "2099-07-01"          # 最早出现日
        assert kn["mcp"]["source_date"] == "2099-07-05"         # 最近笔记日(跳转用)
        assert kn["rag"]["first_seen"] == "2099-07-01"
        assert kn["mcp"]["review_count"] == 0 and kn["mcp"]["ease_factor"] == 2.5
        assert kn["mcp"]["last_review_ts"] is None              # 从未复习过
        assert _read(os.path.join(d, "daily", "knowledge.json"))["knowledge"]  # 已落盘
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sync_idempotent_and_advances_source_not_history():
    d = _dir_with_notes({"2099-07-01": _note("A", ["mcp"])})
    try:
        data1, added1 = sync_from_analysis(d, today=TODAY)
        mark_reviewed(d, "mcp", now=datetime.datetime(2099, 7, 3, 8, 0))
        data2, added2 = sync_from_analysis(d, today=TODAY)
        assert added1 == 1 and added2 == 0                      # 二次同步不重复建档
        m = data2["knowledge"]["mcp"]
        assert m["first_seen"] == "2099-07-01"
        assert m["review_count"] == 1                           # 复习史不被同步抹掉
        # 之后新笔记出现: source_date 推进, 其余不动
        _write(os.path.join(d, "daily", "analysis.json"),
               {"notes": {"2099-07-01": _note("A", ["mcp"]),
                          "2099-07-09": _note("C", ["mcp"])}})
        data3, _ = sync_from_analysis(d, today=TODAY)
        m3 = data3["knowledge"]["mcp"]
        assert m3["source_date"] == "2099-07-09" and m3["review_count"] == 1
        assert m3["first_seen"] == "2099-07-01"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sync_tolerates_missing_or_empty_analysis():
    d = tempfile.mkdtemp()
    try:
        data, added = sync_from_analysis(d, today=TODAY)
        assert added == 0 and data["knowledge"] == {}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 间隔表 ----------------
def test_interval_table_progression():
    rec = {"review_count": 0, "ease_factor": 2.5}
    seen = []
    for expect in INTERVALS:                                    # 1,2,4,7,15,30
        assert interval_days(rec) == expect, (rec, expect)
        seen.append(interval_days(rec))
        rec = dict(rec, review_count=rec["review_count"] + 1)
    assert seen == [1, 2, 4, 7, 15, 30]
    rec["review_count"] = 99                                    # 封顶不再增长
    assert interval_days(rec) == 30


def test_ease_factor_scales_interval_both_directions():
    low = {"review_count": 2, "ease_factor": 1.3}               # 掌握差: 间隔缩短
    high = {"review_count": 2, "ease_factor": 3.0}              # 掌握好: 间隔拉长
    assert interval_days(low) < interval_days({"review_count": 2, "ease_factor": 2.5})
    assert interval_days(high) > interval_days({"review_count": 2, "ease_factor": 2.5})
    assert interval_days(low) >= 1                              # 下限保底一天


# ---------------- 复习打分 ----------------
def test_mark_reviewed_updates_fields_and_rejects_unknown():
    d = _dir_with_notes({"2099-07-01": _note("A", ["mcp"])})
    try:
        sync_from_analysis(d, today=TODAY)
        ok = mark_reviewed(d, "mcp", now=datetime.datetime(2099, 7, 11, 9, 30), quality=5)
        assert ok is True
        m = load_knowledge(d)["knowledge"]["mcp"]
        assert m["review_count"] == 1
        assert m["last_review_ts"] == "2099-07-11T09:30:00"
        assert m["ease_factor"] > 2.5                            # 答得好 ease 上调
        assert mark_reviewed(d, "不存在的概念") is False          # 未建档概念拒绝
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ease_clamped_on_extreme_qualities():
    d = _dir_with_notes({"2099-07-01": _note("A", ["x"]), "2099-07-01b": _note("B", ["y"])})
    try:
        sync_from_analysis(d, today=TODAY)
        for _ in range(20):
            mark_reviewed(d, "x", quality=0, now=datetime.datetime(2099, 7, 5, 8, 0))
            mark_reviewed(d, "y", quality=5, now=datetime.datetime(2099, 7, 5, 8, 0))
        kn = load_knowledge(d)["knowledge"]
        assert kn["x"]["ease_factor"] == 1.3, kn["x"]           # 连续答砸: 钳在下限
        assert kn["y"]["ease_factor"] == 3.0                    # 连续答好: 钳在上限
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 到期与衰减 ----------------
def test_never_reviewed_due_after_first_interval():
    d = _dir_with_notes({"2099-07-10": _note("今天学的", ["fresh"]),
                         "2099-07-08": _note("前天学的", ["stale"])})
    try:
        sync_from_analysis(d, today=TODAY)
        cards = {c["concept"]: c for c in due_cards(d, today=TODAY)}
        assert "stale" in cards, "隔了2天未复习必须到期"
        assert "fresh" not in cards, "当天刚学不该立刻进复习队列(D+1 才开始)"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_due_after_effective_interval_and_overdue_flag():
    d = _dir_with_notes({"2099-07-01": _note("A", ["k"])})
    try:
        sync_from_analysis(d, today=TODAY)
        # 第一次复习于 7-03, 间隔=1天(ease 2.5) -> 7-04 应再到期
        mark_reviewed(d, "k", now=datetime.datetime(2099, 7, 3, 8, 0))
        cards = {c["concept"]: c for c in due_cards(d, today=TODAY)}   # TODAY=7-10
        c = cards["k"]
        assert c["overdue_days"] >= 5 and c["status"] == "已逾期", c
        # 刚复习完的当天不应再出现在到期队列
        mark_reviewed(d, "k", now=datetime.datetime(2099, 7, 10, 8, 0))
        assert all(x["concept"] != "k" for x in due_cards(d, today=TODAY))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_due_cards_sorted_weakest_first():
    d = _dir_with_notes({"2099-07-01": _note("A", ["aaa", "bbb"])})
    try:
        sync_from_analysis(d, today=TODAY)
        mark_reviewed(d, "aaa", quality=0, now=datetime.datetime(2099, 7, 2, 8, 0))  # ease 跌
        mark_reviewed(d, "bbb", quality=5, now=datetime.datetime(2099, 7, 2, 8, 0))
        cards = due_cards(d, today=TODAY)
        rets = [c["retention"] for c in cards]
        assert rets == sorted(rets), cards                       # 衰减最多的排最前
        assert cards[0]["concept"] == "aaa"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_retention_monotone_decreasing_with_gap():
    fresh = {"first_seen": "2099-07-10", "last_review_ts": "2099-07-10T08:00:00",
             "review_count": 1, "ease_factor": 2.5}
    r_now = retention_percent(fresh, today=TODAY)                # gap=0
    old = dict(fresh, last_review_ts="2099-06-01T08:00:00")
    r_old = retention_percent(old, today=TODAY)                  # gap 很大
    assert r_now >= 95 and r_old <= 40, (r_now, r_old)
    mid = dict(fresh, last_review_ts="2099-07-05T08:00:00")
    assert r_now > retention_percent(mid, today=TODAY) > r_old   # 单调递减


def test_decay_rows_respects_topn_and_shape():
    notes = {}
    for i in range(25):
        notes["2099-07-%02d" % (i + 1)] = _note("n%d" % i, ["c%02d" % i])
    d = _dir_with_notes(notes)
    try:
        sync_from_analysis(d, today=TODAY)
        rows = decay_rows(d, today=TODAY, top_n=20)
        assert len(rows) == 20
        assert set(rows[0].keys()) >= {"concept", "retention", "review_count", "interval"}
        rets = [r["retention"] for r in rows]
        assert rets == sorted(rets)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 存取容错 ----------------
def test_load_tolerates_missing_or_broken_file(tmpdir=None):
    d = tempfile.mkdtemp()
    broken = tempfile.mkdtemp()
    try:
        assert load_knowledge(d)["knowledge"] == {}
        os.makedirs(os.path.join(broken, "daily"))
        with open(os.path.join(broken, "daily", "knowledge.json"), "w",
                  encoding="utf-8") as f:
            f.write("{半截")
        assert load_knowledge(broken)["knowledge"] == {}         # 损坏按空档案处理
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(broken, ignore_errors=True)


def test_save_roundtrip():
    d = tempfile.mkdtemp()
    try:
        data = {"version": 1, "knowledge": {"k": {"first_seen": "2099-07-01"}}}
        save_knowledge(d, data)
        assert _read(os.path.join(d, "daily", "knowledge.json")) == data
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
