# -*- coding: utf-8 -*-
"""adaptive_feedback_test.py —— Phase E-B/E-D 多信号自适应反馈聚焦测试
跑法A: pytest adaptive_feedback_test.py   跑法B: python adaptive_feedback_test.py (零依赖runner)
覆盖(E-B): 空日不进 history / carry_over_rate / review_completion_ratio /
          compose_factor 合成与钳制 / 缺信号退化 / 诊断持久化 / 端到端预算
覆盖(E-D): 顺延 3 日窗口均值 / 缺失日与空桶安全 / legacy 单日 / 连续线性惩罚
          (0.3~0.5) / 单调性 / 矛盾信号 / 疲劳+高完成 / 稀疏历史 / 预算下限不变
"""
import datetime
import os
import shutil
import tempfile

from adaptive import (carry_over_rate, review_completion_ratio,
                      compose_factor, evaluate, apply_factor)
from planner import append_history


# ---------- 1. 空日不进 history(rate 污染修复) ----------
def test_1_empty_day_not_appended():
    st = {"history": []}
    r = append_history(st, "2099-01-01", 0, 0)
    assert r is None, r
    assert st["history"] == [], "空日不应写入 history"
    r2 = append_history(st, "2099-01-02", 3, 2)
    assert r2["rate"] == round(2 / 3, 4), r2
    assert len(st["history"]) == 1, st


# ---------- 2. carry_over_rate 聚合 ----------
def test_2_carry_over_rate():
    st = {"days": {"2099-01-01": [
        {"id": "a", "carried": True}, {"id": "b", "carried": True},
        {"id": "c", "carried": False}]}}
    assert carry_over_rate(st) == round(2 / 3, 4)
    st2 = {"days": {"2099-01-01": [{"id": "a"}, {"id": "b"}]}}
    assert carry_over_rate(st2) == 0.0
    assert carry_over_rate({"days": {}}) is None
    assert carry_over_rate({"days": {"2099-01-01": []}}) is None


# ---------- 3. review_completion_ratio 启发式 ----------
def test_3_review_completion_ratio():
    d = tempfile.mkdtemp(prefix="afb_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    try:
        import forgetting
        kn = {"version": 1, "knowledge": {
            "mcp": {"first_seen": "2026-08-20", "source_date": "2026-08-20",
                    "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}},
            "review_log": [{"ts": "2026-08-28T10:00:00", "concept": "mcp", "quality": 4}]}
        forgetting.save_knowledge(d, kn)
        today = datetime.date(2026, 9, 1)
        r = review_completion_ratio(d, today=today)
        assert r is not None and 0.0 <= r <= 1.0, r
        kn2 = {"version": 1, "knowledge": {}, "review_log": []}
        forgetting.save_knowledge(d, kn2)
        assert review_completion_ratio(d, today=today) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- 4. compose_factor 多信号合成与钳制 ----------
def test_4_compose_factor_synthesis():
    assert compose_factor(1.0, carry_over=1.0) == round(1.0 - 0.20, 4)
    assert compose_factor(1.0, carry_over=0.5) == round(1.0 - 0.20, 4)
    assert compose_factor(1.0, carry_over=0.3) == 1.0      # 下限以下不触发
    assert compose_factor(1.0, fatigue=True) == round(0.85, 4)
    assert compose_factor(1.0, review_ratio=0.3) == round(0.90, 4)
    f = compose_factor(1.1, carry_over=1.0, fatigue=True)
    expected = round(round(max(0.6, min(1.3, 1.1 - 0.20)), 4) * 0.85, 4)
    assert f == expected, (f, expected)
    assert compose_factor(1.0, carry_over=1.0, fatigue=True, review_ratio=0.1) >= 0.6
    assert compose_factor(1.3, carry_over=0.3) == 1.3
    assert compose_factor(1.5, carry_over=0.3) <= 1.3


# ---------- 5. 缺信号退化为完成率单信号 ----------
def test_5_missing_signals_degrade():
    assert compose_factor(1.0) == 1.0
    assert compose_factor(1.1) == 1.1
    assert compose_factor(1.0, carry_over=None, fatigue=False, review_ratio=None) == 1.0


# ---------- 6. persist_compose_diagnostic 持久化 ----------
def test_6_persist_compose_diagnostic():
    from _app import services
    st = {"history": [{"date": "2099-01-01", "total": 2, "done": 1, "rate": 0.5}]}
    ok = services.persist_compose_diagnostic(st, {"requested_budget": 5, "final_count": 7})
    assert ok and st["history"][-1]["budget"] == 5 and st["history"][-1]["final"] == 7, st
    assert services.persist_compose_diagnostic({"history": []}, {}) is False
    assert st["history"][-1]["rate"] == 0.5, st


# ---------- 7. 端到端: 合成 factor 进入预算 ----------
def test_7_fused_factor_feeds_budget():
    from adaptive import recent_rates
    st = {"days": {"2099-01-01": [{"id": "a", "carried": True},
                                  {"id": "b", "carried": True}]},
          "history": [{"date": "2099-01-01", "total": 2, "done": 0, "rate": 0.0},
                      {"date": "2099-01-02", "total": 2, "done": 0, "rate": 0.0}]}
    ad = evaluate(recent_rates(st), {})                  # 连续2日 0.0 -> ease 0.8
    assert ad["state"] == "ease" and ad["factor"] == 0.8, ad
    fused = compose_factor(ad["factor"], carry_over=carry_over_rate(st))
    assert fused < ad["factor"], (fused, ad["factor"])
    budget = apply_factor(5, fused)
    assert 1 <= budget <= 5, budget


# ---------------- Phase E-D: 顺延窗口化与阈值平滑 ----------------

# 1. 3 日窗口顺延均值
def test_ed1_three_day_window_average():
    st = {"days": {
        "2099-01-01": [{"id": "a", "carried": True}],                      # 1.0
        "2099-01-02": [{"id": "b", "carried": True}, {"id": "c", "carried": False}],  # 0.5
        "2099-01-03": [{"id": "d", "carried": False}],                      # 0.0
    }}
    assert carry_over_rate(st, window=3) == round((1.0 + 0.5 + 0.0) / 3, 4)


# 2. 缺失历史日安全
def test_ed2_missing_days_skipped():
    st = {"days": {
        "2099-01-01": [{"id": "a", "carried": True}],                      # 1.0
        "2099-01-03": [{"id": "b", "carried": False}],                      # 0.0 (01-02 缺失)
    }}
    assert carry_over_rate(st, window=3) == 0.5


# 3. 空历史桶安全
def test_ed3_empty_buckets_skipped():
    st = {"days": {
        "2099-01-01": [],
        "2099-01-02": [{"id": "b", "carried": True}],
        "2099-01-03": [],
    }}
    assert carry_over_rate(st, window=3) == 1.0
    assert carry_over_rate({"days": {}}) is None
    assert carry_over_rate({"days": {"2099-01-01": []}}) is None


# 4. legacy 单日行为保留
def test_ed4_legacy_single_day():
    st = {"days": {
        "2099-01-01": [{"id": "a", "carried": True}],
        "2099-01-02": [{"id": "b", "carried": False}],
    }}
    assert carry_over_rate(st, date="2099-01-01") == 1.0
    assert carry_over_rate(st, date="2099-01-02") == 0.0
    assert carry_over_rate(st, window=1) == 0.0          # 最近 1 个含任务桶


# 5. 阈值低于下界
def test_ed5_threshold_below_lower():
    assert compose_factor(1.0, carry_over=0.29) == 1.0
    assert compose_factor(1.0, carry_over=0.0) == 1.0


# 6. 阈值在下界
def test_ed6_threshold_at_lower():
    assert compose_factor(1.0, carry_over=0.3) == 1.0    # 下界处 0 惩罚


# 7. 阈值 0.39
def test_ed7_threshold_at_039():
    f039 = compose_factor(1.0, carry_over=0.39)
    assert f039 < 1.0, f039
    assert f039 == round(1.0 - round((0.39 - 0.3) / 0.2 * 0.20, 4), 4), f039


# 8. 阈值 0.40(无阶跃)
def test_ed8_threshold_at_040():
    f039 = compose_factor(1.0, carry_over=0.39)
    f040 = compose_factor(1.0, carry_over=0.40)
    assert f040 <= f039, (f040, f039)                    # 惩罚随顺延增大, factor 递减
    assert f040 == round(1.0 - 0.10, 4), f040            # (0.1/0.2)*0.2=0.10


# 9. 阈值在上界
def test_ed9_threshold_at_upper():
    assert compose_factor(1.0, carry_over=0.5) == round(1.0 - 0.20, 4)


# 10. 阈值高于上界
def test_ed10_threshold_above_upper():
    assert compose_factor(1.0, carry_over=0.6) == round(1.0 - 0.20, 4)
    assert compose_factor(1.0, carry_over=1.0) == round(1.0 - 0.20, 4)


# 11. 单调惩罚递进
def test_ed11_monotonic_penalty():
    prev = None
    for co in (0.0, 0.2, 0.3, 0.31, 0.35, 0.39, 0.40, 0.45, 0.5, 0.6, 0.8, 1.0):
        f = compose_factor(1.0, carry_over=co)
        if prev is not None:
            assert f <= prev, (co, f, prev)              # 惩罚不减, factor 不增
        prev = f
    p = [round(1.0 - compose_factor(1.0, carry_over=co), 4) for co in
         (0.3, 0.35, 0.40, 0.45, 0.50)]
    assert p == sorted(p), p


# 12. 高完成 + 高顺延
def test_ed12_high_completion_high_carry():
    f = compose_factor(1.1, carry_over=1.0)
    assert f < 1.0 and f == round(1.1 - 0.20, 4), f      # 清欠优先, 减量


# 13. 疲劳 + 高完成
def test_ed13_fatigue_high_completion():
    f = compose_factor(1.1, fatigue=True)
    assert f == round(1.1 * 0.85, 4), f                  # 0.935


# 14. 稀疏历史(仅主信号)
def test_ed14_sparse_history():
    assert compose_factor(1.0) == 1.0
    assert compose_factor(0.8) == 0.8


# 15. predicted 预算下限交互不变
def test_ed15_predicted_floor_unchanged():
    assert apply_factor(1, 0.8) == 1                     # 下限保 1 语义不变
    assert apply_factor(1, 1.3) == 1
    assert apply_factor(5, 0.6) == 3
    assert apply_factor(0, 0.6) == 1                     # predicted 0 -> 保 1


# 16. 窗口化: 仅 1 个可用日(不放大单日, 返回该日值)
def test_ed16_only_one_recent_day():
    st = {"days": {
        "2099-01-01": [],
        "2099-01-02": [{"id": "a", "carried": True}, {"id": "b", "carried": False}],
        "2099-01-03": [],
    }}
    assert carry_over_rate(st, window=3) == 0.5           # 只有 01-02 一个含任务日


# 17. 低完成 + 高顺延(双负叠加, 单调减)
def test_ed17_low_completion_high_carry():
    f = compose_factor(0.8, carry_over=1.0)
    assert f == round(0.8 - 0.20, 4), f                  # 0.60
    assert 0.6 <= f <= 0.8, f
    f2 = compose_factor(0.8, carry_over=1.0, fatigue=True, review_ratio=0.1)
    assert f2 == round(round(0.6, 4) * 0.85 * 0.90, 4) or f2 >= 0.6, f2  # 触下限


# 18. 确定性: 重复调用结果一致
def test_ed18_deterministic_repeat():
    args = (1.1, 0.45, True, 0.3)
    a = compose_factor(*args)
    for _ in range(5):
        assert compose_factor(*args) == a
    st = {"days": {"2099-01-01": [{"id": "x", "carried": True}] * 3}}
    r1 = carry_over_rate(st)
    for _ in range(5):
        assert carry_over_rate(st) == r1


# 19. 回归: factor 全范围有界 + 惩罚不转正 + 顺延增则 factor 不增
def test_ed19_factor_bounded_monotonic():
    for base in (0.6, 0.8, 1.0, 1.1, 1.3, 1.5):
        for co in (0.0, 0.3, 0.39, 0.5, 1.0):
            for fat in (False, True):
                f = compose_factor(base, carry_over=co, fatigue=fat, review_ratio=0.0)
                assert 0.6 <= f <= 1.3, (base, co, fat, f)
    # 惩罚永不为正(即 factor 不被 carry_over 抬高)
    for co in (0.0, 0.3, 0.5, 1.0):
        assert compose_factor(1.0, carry_over=co) <= 1.0, co
    # 顺延单调: co 增则 factor 不增
    prev = 2.0
    for co in (0.0, 0.1, 0.29, 0.3, 0.35, 0.4, 0.45, 0.5, 0.75, 1.0):
        f = compose_factor(1.1, carry_over=co)
        assert f <= prev + 1e-9, (co, f, prev)
        prev = f


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
