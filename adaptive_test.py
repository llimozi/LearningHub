# -*- coding: utf-8 -*-
"""adaptive_test.py —— 学习节奏自适应单元测试 (v1.2 · 纯标准库)
跑法A: pytest adaptive_test.py      跑法B: python adaptive_test.py (零依赖runner)
覆盖: 连续高完成率加量(+10%)与连击判定 / 连续低完成率减量(-20%)+休息建议 /
      中间值打断连击 / 边界值(0.9算高、0.5算低) / 开关关闭 / 自定义参数 /
      应用系数的下限保护 / 从 tasks history 取近端序列。
"""
try:                                    # 软依赖: 有 pytest 走 A 路, 无则进 B 路
    import pytest                        # noqa: F401  (本套件无 fixture/parametrize, 仅占位)
except ImportError:
    pytest = None                        # 标记为零依赖模式, 测试主体仍走标准 assert

import tempfile

from adaptive import (DEFAULT_ADAPTIVE, evaluate, apply_factor,
                      recent_rates)


def _cfg(**kw):
    base = dict(DEFAULT_ADAPTIVE)
    base.update(kw)
    return base


# ---------------- 加量 ----------------
def test_three_strong_days_boost_next_day():
    out = evaluate([0.9, 1.0, 0.95])
    assert out["state"] == "boost" and abs(out["factor"] - 1.10) < 1e-9, out
    assert out["rest_hint"] is False


def test_two_strong_days_not_enough():
    out = evaluate([1.0, 0.95])
    assert out["state"] == "flat" and out["factor"] == 1.0, out


def test_mid_rate_breaks_high_run():
    # 末尾是 0.6 -> 打断连击, 即使前面有三个高日也不加量
    out = evaluate([0.95, 0.95, 0.95, 0.6])
    assert out["state"] == "flat", out


# ---------------- 减量 ----------------
def test_two_low_days_ease_with_rest_hint():
    out = evaluate([0.4, 0.5])
    assert out["state"] == "ease" and abs(out["factor"] - 0.80) < 1e-9, out
    assert out["rest_hint"] is True


def test_single_low_day_flat():
    out = evaluate([0.9, 0.3])
    assert out["state"] == "flat" and out["rest_hint"] is False, out


def test_boundary_inclusive_09_and_05():
    assert evaluate([0.9, 0.9, 0.9])["state"] == "boost"       # >=0.9 算高
    assert evaluate([0.5, 0.5])["state"] == "ease"             # <=0.5 算低
    assert evaluate([0.89, 0.89, 0.89])["state"] == "flat"
    assert evaluate([0.51, 0.51])["state"] == "flat"


# ---------------- 开关与自定义 ----------------
def test_disabled_returns_off():
    out = evaluate([1.0, 1.0, 1.0], _cfg(enabled=False))
    assert out["state"] == "off" and out["factor"] == 1.0, out


def test_custom_params_honored():
    cfg = _cfg(high_run=2, high_rate=0.8, boost=0.5)
    out = evaluate([0.85, 0.85], cfg)
    assert out["state"] == "boost" and abs(out["factor"] - 1.5) < 1e-9, out
    cfg2 = _cfg(low_run=3)
    assert evaluate([0.4, 0.4], cfg2)["state"] == "flat"       # 需要连3天才触发


def test_empty_history_flat_no_crash():
    out = evaluate([])
    assert out["state"] == "flat" and out["factor"] == 1.0 and out["reason"], out


# ---------------- 应用到预测 ----------------
def test_apply_factor_rounds_and_keeps_min_one():
    assert apply_factor(3, 1.10) == 3                          # 3.3 -> 3
    assert apply_factor(10, 1.50) == 15
    assert apply_factor(1, 0.80) == 1                          # 减量后不许低于 1 条
    assert apply_factor(4, 0.80) == 3                          # 3.2 -> 3


# ---------------- 与 tasks.json 的桥 ----------------
def test_recent_rates_reads_history_tail_ascending():
    st = {"history": [
        {"date": "2099-07-01", "total": 2, "done": 2, "rate": 1.0},
        {"date": "2099-07-02", "total": 2, "done": 0, "rate": 0.0},
        {"date": "2099-07-03", "total": 2, "done": 1, "rate": 0.5},
        {"date": "2099-07-04", "total": 2, "done": 2, "rate": 1.0},
    ]}
    assert recent_rates(st, n=3) == [0.0, 0.5, 1.0]            # 升序取尾
    assert recent_rates(st, n=10) == [1.0, 0.0, 0.5, 1.0]      # n 超长全量
    assert recent_rates({"history": []}) == []


def test_settings_defaults_contain_adaptive_block():
    import settings as settings_mod
    d = settings_mod.load_settings(tempfile.mkdtemp())
    assert d["adaptive"]["enabled"] is True
    assert d["adaptive"]["boost"] == 0.10 and d["adaptive"]["reduce"] == 0.20


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
