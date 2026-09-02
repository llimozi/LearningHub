# -*- coding: utf-8 -*-
"""weakspot_test.py —— 周日薄弱点自动分析单元测试 (v1.2 · 纯标准库)
跑法A: pytest weakspot_test.py      跑法B: python weakspot_test.py (零依赖runner)
覆盖: 只在周日运行 / 报告以「下周周一」为档名天然幂等 / 最低5个概念入报告 /
      专项练习任务插入下周桶(确定性id去重, 跨天也不重复) / 全员健康则只出报告不插任务 /
      插入不破坏既有字段。全部临时目录+固定日期。
"""
import datetime
import json
import os
import shutil
import tempfile

import weakspot

SUNDAY = datetime.date(2099, 7, 19)          # 实测 weekday()==6 的周日
NEXT_MONDAY = SUNDAY + datetime.timedelta(days=1)
STALE_DAY = (SUNDAY - datetime.timedelta(days=25)).isoformat()


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _dir_with_stale(concepts=("荒废A", "荒废B")):
    """造一个含久未复习概念的目录(含空任务库) -> 这些概念必然掉进红队"""
    d = tempfile.mkdtemp()
    notes = {STALE_DAY: {"topic": "旧课", "concepts": list(concepts),
                         "tags": [], "code_langs": []}}
    _write(os.path.join(d, "daily", "analysis.json"), {"notes": notes})
    _write(os.path.join(d, "tasks.json"),
           {"version": 3, "days": {}, "history": [], "fatigue": {}, "log": []})
    from forgetting import sync_from_analysis
    sync_from_analysis(d, today=SUNDAY)
    return d


# ---------------- 触发条件 ----------------
def test_non_sunday_never_runs():
    d = _dir_with_stale()
    try:
        out = weakspot.weekly_analysis(d, today=SUNDAY - datetime.timedelta(days=1))
        assert out["ran"] is False and "周日" in out["reason"], out
        assert not any(f.startswith("weakness_")
                       for f in os.listdir(os.path.join(d, "reports"))) \
            if os.path.isdir(os.path.join(d, "reports")) else True
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 主流程 ----------------
def test_sunday_creates_report_and_inserts_next_monday_tasks():
    d = _dir_with_stale(("荒废A", "荒废B"))
    try:
        out = weakspot.weekly_analysis(d, today=SUNDAY)
        assert out["ran"] is True, out
        rname = "weakness_" + NEXT_MONDAY.strftime("%Y%m%d") + ".md"
        rp = os.path.join(d, "reports", rname)
        assert os.path.exists(rp), (out, rname)
        body = open(rp, encoding="utf-8").read()
        assert "# 薄弱点专项分析" in body and "荒废A" in body and "荒废B" in body
        assert "| 知识点 |" in body                                  # 表格结构在
        st = _read(os.path.join(d, "tasks.json"))
        bucket = st["days"].get(NEXT_MONDAY.isoformat()) or []
        ids = [t["id"] for t in bucket]
        texts = [t["text"] for t in bucket]
        assert len(ids) == 2, ids                                   # 两个红队概念各一条
        assert all(i.startswith("w-") for i in ids)
        assert any("荒废A" in t for t in texts)
        assert all(t.get("priority") == 1 for t in bucket)          # 专项练习高优
        events = [e for e in st.get("log", []) if e.get("event") == "weakness_insert"]
        assert len(events) == 1, events                             # 插入留账
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_second_run_same_sunday_is_idempotent():
    d = _dir_with_stale(("荒废A",))
    try:
        out1 = weakspot.weekly_analysis(d, today=SUNDAY)
        tasks_before = json.dumps(_read(os.path.join(d, "tasks.json")),
                                  sort_keys=True, ensure_ascii=False)
        files_before = sorted(os.listdir(os.path.join(d, "reports")))
        out2 = weakspot.weekly_analysis(d, today=SUNDAY)
        tasks_after = json.dumps(_read(os.path.join(d, "tasks.json")),
                                 sort_keys=True, ensure_ascii=False)
        files_after = sorted(os.listdir(os.path.join(d, "reports")))
        assert out2["already_done"] is True and out2["ran"] is False, out2
        assert tasks_before == tasks_after and files_before == files_after
        assert out1["ran"] is True and len(out1["added"]) >= 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_all_healthy_writes_report_but_no_tasks():
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "daily", "analysis.json"),
           {"notes": {(SUNDAY - datetime.timedelta(days=1)).isoformat():
                      {"topic": "新课", "concepts": ["新鲜概念"],
                       "tags": [], "code_langs": []}}})
    _write(os.path.join(d, "tasks.json"),
           {"version": 3, "days": {}, "history": [], "fatigue": {}, "log": []})
    try:
        from forgetting import sync_from_analysis
        sync_from_analysis(d, today=SUNDAY)
        out = weakspot.weekly_analysis(d, today=SUNDAY)
        assert out["ran"] is True and out["concepts"] == [], out     # 保护期内不算薄弱
        rp = os.path.join(d, "reports",
                          "weakness_" + NEXT_MONDAY.strftime("%Y%m%d") + ".md")
        assert os.path.exists(rp)                                    # 报告照常立档
        assert "无薄弱点" in open(rp, encoding="utf-8").read()
        assert not (_read(os.path.join(d, "tasks.json"))
                    .get("days", {}).get(NEXT_MONDAY.isoformat())), "不应插任何任务"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_max_five_cap():
    d = _dir_with_stale(tuple("概念%d号" % i for i in range(8)))       # 8 个全红
    try:
        out = weakspot.weekly_analysis(d, today=SUNDAY)
        assert len(out["concepts"]) == 5, out                        # 只取最低 5 个
        assert len(out["added"]) == 5
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_deterministic_task_id_dedupes_across_buckets():
    d = _dir_with_stale(("荒废A",))
    try:
        tid = weakspot.task_id("荒废A")
        st_path = os.path.join(d, "tasks.json")
        st = _read(st_path)
        st.setdefault("days", {}).setdefault("2099-07-01", []).append(
            {"id": tid, "text": "早前手工排过同款", "done": False,
             "carried": False, "src_date": "2099-07-01", "priority": 2})
        _write(st_path, st)
        out = weakspot.weekly_analysis(d, today=SUNDAY)
        assert out["added"] == [] and len(out["skipped"]) == 1, out  # 跨桶同id视为已安排
        st2 = _read(st_path)
        total = sum(1 for b in st2["days"].values() for t in b if t["id"] == tid)
        assert total == 1, total                                     # 全库只有一条
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_insertion_preserves_existing_fields():
    d = _dir_with_stale(("荒废A",))
    try:
        st_path = os.path.join(d, "tasks.json")
        st = _read(st_path)
        st["history"] = [{"date": STALE_DAY, "total": 1, "done": 1, "rate": 1.0}]
        st["fatigue"] = {"active": True, "since": STALE_DAY, "reason": "测试"}
        _write(st_path, st)
        weakspot.weekly_analysis(d, today=SUNDAY)
        st2 = _read(st_path)
        assert st2["history"][0]["rate"] == 1.0                      # history 原样
        assert st2["fatigue"]["active"] is True                      # fatigue 原样
        assert any(t["text"] != "" for b in st2["days"].values()
                   for t in b if t["id"].startswith("w-"))
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
