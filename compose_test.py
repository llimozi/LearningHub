# -*- coding: utf-8 -*-
"""compose_test.py —— Phase B 明日预算闭环 compose_tomorrow 聚焦测试
跑法A: pytest compose_test.py      跑法B: python compose_test.py (零依赖runner)
覆盖(Phase B 规格 §11):
  A 预算补足 / B 预算钳制(既有>=预算零生成) / C 幂等 / D 确定性id / E 全库去重 /
  F 无task_pool优雅降级 / G 优先级+优先窗口排序 / H 既有rollover任务保全 /
  I 零/负/非法budget / J 组合仅走 POST rollover 路径(源码级断言 + 功能反证)
"""
import datetime
import inspect

from _app import services
from _app.server import Handler

TODAY = "2099-01-01"
TOM = "2099-01-02"


def mk_task(tid, pri=2, done=False, carried=False):
    return {"id": tid, "text": "既有任务" + tid, "done": done,
            "carried": carried, "src_date": TODAY, "priority": pri}


def mk_state(existing_tomorrow):
    return {"days": {TODAY: [], TOM: list(existing_tomorrow)}}


def pool_line(lid, items, name="线"):
    return {"id": lid, "name": name, "task_pool": items}


def item(text, pri=2, **kw):
    d = {"text": text, "priority": pri}
    d.update(kw)
    return d


def three_pool_plan():
    return mk_plan([pool_line("A", [item("任务甲", 2), item("任务乙", 2), item("任务丙", 2)])])


def mk_plan(lines, windows=None):
    return {"version": 1, "lines": lines, "priority_windows": windows or []}


# ---------- A. 预算补足: 既有2 预算5 -> 恰好补3, 既有保全 ----------
def test_a_budget_fill():
    existing = [mk_task("e1"), mk_task("e2")]
    st = mk_state(existing)
    out = services.compose_tomorrow(st, TOM, 5, cfg={"plan": three_pool_plan()})
    assert out["generated_count"] == 3, out
    assert out["final_count"] == 5, out
    assert out["remaining_slots"] == 3, out
    # 既有任务原地保全且在前
    assert [t["id"] for t in st["days"][TOM]][:2] == ["e1", "e2"], st["days"][TOM]
    for t in existing:
        assert t in st["days"][TOM], t


# ---------- B. 预算钳制: 既有5 预算3 -> 零生成, 既有不动 ----------
def test_b_budget_clamp():
    existing = [mk_task("e%d" % i) for i in range(5)]
    st = mk_state(existing)
    snapshot = [dict(t) for t in st["days"][TOM]]
    out = services.compose_tomorrow(st, TOM, 3, cfg={"plan": three_pool_plan()})
    assert out["generated_count"] == 0, out
    assert out["final_count"] == 5, out
    assert st["days"][TOM] == snapshot, "既有任务被改动"


# ---------- C. 幂等: 同输入连调两次, 第二次零新增 ----------
def test_c_idempotent():
    st = mk_state([mk_task("e1")])
    r1 = services.compose_tomorrow(st, TOM, 4, cfg={"plan": three_pool_plan()})
    assert r1["generated_count"] == 3, r1
    n1 = len(st["days"][TOM])
    r2 = services.compose_tomorrow(st, TOM, 4, cfg={"plan": three_pool_plan()})
    assert r2["generated_count"] == 0, r2
    assert len(st["days"][TOM]) == n1, st["days"][TOM]


# ---------- D. 确定性身份: 同线/同文/同日期 -> 同 id ----------
def test_d_deterministic_identity():
    s1 = mk_state([])
    o1 = services.compose_tomorrow(s1, TOM, 9, cfg={"plan": three_pool_plan()})
    s2 = mk_state([])
    o2 = services.compose_tomorrow(s2, TOM, 9, cfg={"plan": three_pool_plan()})
    assert [g["id"] for g in o1["generated"]] == [g["id"] for g in o2["generated"]], (o1, o2)
    assert all(g["id"].startswith("c-") for g in o1["generated"]), o1
    # 直接调用 id 生成器复核稳定性
    a = services._compose_task_id("A", "任务甲", "基础", None)
    b = services._compose_task_id("A", "任务甲", "基础", None)
    c = services._compose_task_id("A", "任务甲", "强化", None)
    assert a == b and a != c, (a, b, c)


# ---------- E. 全库去重: 同 id 任务已存在于其他桶 -> 不再生成 ----------
def test_e_global_dedup():
    plan = mk_plan([pool_line("A", [item("独苗任务", 1)])])
    tid = services._compose_task_id("A", "独苗任务", None, None)
    st = mk_state([])
    st["days"][TODAY] = [{"id": tid, "text": "独苗任务", "done": True,
                          "carried": False, "src_date": TODAY, "priority": 1}]
    out = services.compose_tomorrow(st, TOM, 3, cfg={"plan": plan})
    assert out["generated_count"] == 0, out
    assert len(st["days"][TOM]) == 0, st["days"][TOM]


# ---------- F. 无/坏 task_pool -> 优雅降级, 不发明任务 ----------
def test_f_missing_pool():
    plan = mk_plan([
        {"id": "A", "name": "无线"},                                   # 无 task_pool 键
        pool_line("B", []),                                            # 空池
        pool_line("C", ["不是字典", {"priority": 1}, item("   ", 1)]),  # 坏条目/空文本
    ])
    st = mk_state([])
    out = services.compose_tomorrow(st, TOM, 5, cfg={"plan": plan})
    assert out["generated_count"] == 0, out
    assert st["days"][TOM] == [], st["days"][TOM]
    # plan 缺失/坏类型同样降级
    st2 = mk_state([])
    out2 = services.compose_tomorrow(st2, TOM, 5, cfg={"plan": None})
    st3 = mk_state([])
    out3 = services.compose_tomorrow(st3, TOM, 5, cfg={"plan": "坏类型"})
    assert out2["generated_count"] == 0 and out3["generated_count"] == 0, (out2, out3)


# ---------- G. 排序: 高优先级先选; 活动优先窗口的线先于非活动线 ----------
def test_g_priority_and_window_order():
    plan = mk_plan(
        [pool_line("X", [item("活动线任务", 2)]),
         pool_line("Y", [item("非活动线任务", 2)]),
         pool_line("Z", [item("低优先任务", 3)])],
        windows=[{"line": "X", "from": "2099-01-01", "to": "2099-01-03"}])
    st = mk_state([])
    out = services.compose_tomorrow(st, TOM, 9, cfg={"plan": plan})
    ids = [g["text"] for g in out["generated"]]
    assert ids[0] == "活动线任务", ids            # 窗口内 X 线优先
    assert ids[1] == "非活动线任务", ids          # 同优先级: 非活动线在低优先任务之前
    assert ids[2] == "低优先任务", ids
    # 纯优先级: pri1 压过 pri3, 即使它在更后的线
    plan2 = mk_plan([pool_line("P", [item("高优", 1)]),
                     pool_line("Q", [item("低优", 3)])])
    st2 = mk_state([])
    out2 = services.compose_tomorrow(st2, TOM, 1, cfg={"plan": plan2})
    assert out2["generated"][0]["text"] == "高优", out2


# ---------- H. 既有 rollover 任务保全并先计预算 ----------
def test_h_rollover_preserved():
    existing = [mk_task("r1", pri=1, carried=True), mk_task("r2", pri=2, carried=True)]
    st = mk_state(existing)
    snapshot = [dict(t) for t in existing]
    out = services.compose_tomorrow(st, TOM, 3, cfg={"plan": three_pool_plan()})
    assert out["existing_count"] == 2 and out["generated_count"] == 1, out
    assert st["days"][TOM][:2] == snapshot, "rollover 任务被改动或移动"


# ---------- I. 零/负/非法 budget -> 零生成 ----------
def test_i_invalid_budget():
    plan = three_pool_plan()
    for bad in (0, -2, None, "abc"):
        st = mk_state([])
        out = services.compose_tomorrow(st, TOM, bad, cfg={"plan": plan})
        assert out["generated_count"] == 0, (bad, out)
    # 3.9 int() 截断为 3 -> 合法生成 3 条（"整数化"而非拒绝）
    st = mk_state([])
    out_f = services.compose_tomorrow(st, TOM, 3.9, cfg={"plan": plan})
    assert out_f["generated_count"] == 3, out_f


# ---------- J. 组合只走 POST rollover 路径 ----------
def test_j_compose_only_via_post_rollover():
    # 1) 源码级: _post_rollover 必须引用 compose_tomorrow
    src = inspect.getsource(Handler._post_rollover)
    assert "compose_tomorrow" in src, "POST rollover 未接入 compose"
    # 2) 源码级: 禁区不得出现
    for fn in (services.rollover, services.auto_catchup):
        assert "compose_tomorrow" not in inspect.getsource(fn), \
            "%s 内不得调用 compose" % fn.__name__
    # 3) 功能反证: 带任务池的状态跑 rollover / auto_catchup, 不产生 c- 任务
    #    注意 auto_catchup 以真实 config.TODAY 判过期 -> 必须用真实过去的日期
    plan = three_pool_plan()
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    st = {"days": {TODAY: [mk_task("u1", done=False)],
                   old: [mk_task("old1", done=False)]}}
    services.rollover(st, TODAY, persist=False)
    msgs = services.auto_catchup(st, persist=False)
    for bk in st["days"].values():
        for t in bk:
            assert not str(t.get("id", "")).startswith("c-"), t
    assert msgs, "auto_catchup 应已滚动过期桶"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
        except Exception as ex:
            failed += 1
            print("ERROR", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    import sys
    sys.exit(1 if failed else 0)
