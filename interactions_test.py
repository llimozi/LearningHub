# -*- coding: utf-8 -*-
"""interactions_test.py —— v1.3 键盘/拖拽/批量操作的后端单元测试
跑法A: pytest interactions_test.py      跑法B: python interactions_test.py
覆盖: reorder 全列表重排与部分列表尾部保序 / 无桶日期拒收 /
      batch done·delete·priority 三动作计数与留账 / 优先级钳制 /
      空 ids 与未知动作拒收。全部纯函数注入 state, 不碰真实文件。
"""
from build_dashboard import reorder_tasks, batch_tasks


def _st():
    return {"version": 3, "days": {"2099-07-10": [
        {"id": "a", "text": "甲", "done": False, "priority": 2},
        {"id": "b", "text": "乙", "done": False, "priority": 1},
        {"id": "c", "text": "丙", "done": True, "priority": 3},
    ]}, "history": [], "fatigue": {}, "log": []}


def _bucket(st, ds="2099-07-10"):
    return [t["id"] for t in st["days"][ds]]


# ---------------- 拖拽排序 ----------------
def test_reorder_full_list():
    st = _st()
    out = reorder_tasks(st, ["c", "a", "b"], date="2099-07-10")
    assert out["ok"] is True and out["moved"] == 3, out
    assert _bucket(st) == ["c", "a", "b"], _bucket(st)


def test_reorder_partial_keeps_missing_tail_in_original_order():
    st = _st()
    out = reorder_tasks(st, ["c"], date="2099-07-10")     # 只拖了 c 到最前
    assert out["ok"] is True
    assert _bucket(st) == ["c", "a", "b"], _bucket(st)   # 其余保持原相对顺序


def test_reorder_missing_ids_reported_not_fatal():
    st = _st()
    out = reorder_tasks(st, ["zzz", "b", "a"], date="2099-07-10")
    assert out["ok"] is True and out["missing"] == ["zzz"], out
    assert _bucket(st) == ["b", "a", "c"], _bucket(st)


def test_reorder_rejects_empty_or_unknown_bucket():
    st = _st()
    assert reorder_tasks(st, [], date="2099-07-10")["ok"] is False
    assert reorder_tasks(st, ["a"], date="2099-01-01")["ok"] is False


# ---------------- 批量操作 ----------------
def test_batch_done_toggles_many_at_once():
    st = _st()
    out = batch_tasks(st, "done", ["a", "b"], value=True, date="2099-07-10")
    assert out["ok"] is True and out["affected"] == 2, out
    flags = {t["id"]: t["done"] for t in st["days"]["2099-07-10"]}
    assert flags == {"a": True, "b": True, "c": True}, flags
    assert any(e["event"] == "batch_done" for e in st["log"])


def test_batch_delete_removes_and_logs():
    st = _st()
    out = batch_tasks(st, "delete", ["a", "zzz"], date="2099-07-10")
    assert out["ok"] is True and out["affected"] == 1, out
    assert _bucket(st) == ["b", "c"]
    assert any(e["event"] == "batch_delete" and e["count"] == 1 for e in st["log"])


def test_batch_priority_clamped_to_1_3():
    st = _st()
    out = batch_tasks(st, "priority", ["a", "b"], value=9, date="2099-07-10")
    assert out["ok"] is True and out["affected"] == 2
    pris = {t["id"]: t.get("priority") for t in st["days"]["2099-07-10"]}
    assert pris["a"] == 3 and pris["b"] == 3, pris        # 9 被钳到上限 3
    out2 = batch_tasks(st, "priority", ["a"], value=-5, date="2099-07-10")
    assert st["days"]["2099-07-10"][0]["priority"] >= 1


def test_batch_rejects_bad_input():
    st = _st()
    assert batch_tasks(st, "done", [], date="2099-07-10")["ok"] is False          # 空 ids
    assert batch_tasks(st, "变魔术", ["a"], date="2099-07-10")["ok"] is False      # 未知动作
    assert len(st["days"]["2099-07-10"]) == 3                  # 拒收时零改动


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
