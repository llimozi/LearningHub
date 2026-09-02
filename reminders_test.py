# -*- coding: utf-8 -*-
"""reminders_test.py —— 本地通知提醒单元测试 (v1.0 · 纯标准库)
跑法A: pytest reminders_test.py      跑法B: python reminders_test.py (零依赖runner)
覆盖: 三种触发的正反边界(每日首开/复习临近/连续未打开) / 文案动态性断言 /
      fired 防重弹与跨天清理 / run_checks 编排(注入loader, 不碰真实数据文件)
所有用例用 2099 年假日期与固定时刻, 与真实系统时间完全解耦。
"""
import json
import os
import shutil
import tempfile
from datetime import datetime

from reminders import (daily_first_open, review_due, away_return,
                       mark_fired, prune_fired, run_checks)


# ---------------- 固定输入构造 ----------------
def _now(h, m):
    """固定判定时刻: 2099-01-01 HH:MM"""
    return datetime(2099, 1, 1, h, m, 0)


TODAY = "2099-01-01"

TEXTS = ["写周报", "复习 Function Calling", "整理笔记"]


def _bucket(done_flags):
    """按 done 标志生成今日任务桶"""
    return [{"id": "t-%02d" % i, "text": TEXTS[i], "done": d}
            for i, d in enumerate(done_flags)]


def _state(flags):
    return {"days": {TODAY: _bucket(flags)}}


CARDS = [
    {"concept": "Function Calling", "status": "需复习"},
    {"concept": "MCP", "status": "新学"},
    {"concept": "RAG", "status": "需复习"},
]


def _cfg(**kw):
    """复习判定的配置块(默认值与 settings.default_settings 对齐)"""
    base = {"review_near": True, "review_time": "20:00"}
    base.update(kw)
    return base


# ---------------- 每日首次开机 ----------------
def test_daily_first_open_fires_with_undone_tasks():
    fired = {}
    m = daily_first_open(_now(8, 0), _state([True, False, False]), CARDS, fired)
    assert m and m["key"] == "daily", m
    assert "2 条任务未完成" in m["body"], m                  # 未完成计数动态
    assert "复习 Function Calling" in m["body"], m           # 第一条未完成任务原文动态


def test_daily_skips_when_all_done_and_no_review():
    m = daily_first_open(_now(8, 0), _state([True, True, True]), [], {})
    assert m is None, "无事可说就不打扰"


def test_daily_second_call_same_day_no_refire():
    fired = {}
    now = _now(8, 0)
    assert daily_first_open(now, _state([False]), CARDS, fired) is not None
    mark_fired(fired, now, "daily")
    assert daily_first_open(now, _state([False]), CARDS, fired) is None


def test_daily_next_day_fires_again():
    fired = {"2098-12-31": ["daily"]}                        # 昨天弹过, 今天照弹
    m = daily_first_open(_now(8, 0), _state([False]), CARDS, fired)
    assert m is not None, m


def test_daily_body_lists_due_review_concepts():
    m = daily_first_open(_now(8, 0), _state([]), CARDS, {})  # 今日无任务桶
    assert m and "Function Calling" in m["body"] and "RAG" in m["body"], m


def test_daily_copy_is_dynamic():
    a = daily_first_open(_now(8, 0), _state([True, False, False]), CARDS, {})
    b = daily_first_open(_now(8, 0), _state([True, True, False]), CARDS, {})
    assert a["body"] != b["body"], "换输入必须换文案"
    assert "1 条任务未完成" in b["body"], b


# ---------------- 复习临近(<30min) ----------------
def test_review_before_window_silent():
    # 复习时段 20:00, 提前量 30 分钟 -> 19:29 及以前都不弹
    assert review_due(_now(19, 29), _cfg(), CARDS, {}) is None


def test_review_at_window_edge_fires():
    m = review_due(_now(19, 30), _cfg(), CARDS, {})
    assert m and m["key"] == "review", m                     # 19:30 = 20:00 前 30 分钟, 边界即触发
    assert "Function Calling" in m["body"] and "RAG" in m["body"], m


def test_review_after_start_still_fires_once():
    m = review_due(_now(22, 0), _cfg(), CARDS, {})           # 开机晚于时段也要补弹一次
    assert m is not None, m


def test_review_custom_time_respected():
    cfg = _cfg(review_time="08:00")
    assert review_due(_now(7, 29), cfg, CARDS, {}) is None
    assert review_due(_now(7, 31), cfg, CARDS, {}) is not None


def test_review_disabled_silent_even_in_window():
    assert review_due(_now(21, 0), _cfg(review_near=False), CARDS, {}) is None


def test_review_invalid_time_falls_back_to_2000():
    m = review_due(_now(19, 35), _cfg(review_time="25:99"), CARDS, {})
    assert m is not None, "非法时段配置按默认 20:00 处理"


def test_review_no_due_cards_silent():
    cards = [{"concept": "MCP", "status": "新学"}]
    assert review_due(_now(21, 0), _cfg(), cards, {}) is None


def test_review_refire_blocked_by_fired():
    fired = {TODAY: ["review"]}
    assert review_due(_now(21, 0), _cfg(), CARDS, fired) is None


# ---------------- 连续未打开 ----------------
def test_away_exactly_two_days_fires():
    m = away_return(_now(8, 0), "2098-12-30T21:00:00", {}, away_days=2)
    assert m and m["key"] == "away", m                       # 12-30 -> 01-01 整 2 天
    assert "2 天" in m["body"], m                            # 天数动态进文案


def test_away_one_day_silent():
    m = away_return(_now(8, 0), "2098-12-31T09:00:00", {}, away_days=2)
    assert m is None, m


def test_away_five_days_mentions_real_gap():
    m = away_return(_now(8, 0), "2098-12-27T09:00:00", {}, away_days=2)
    assert m and "5 天" in m["body"], m


def test_away_missing_or_garbage_ts_silent():
    assert away_return(_now(8, 0), None, {}, away_days=2) is None
    assert away_return(_now(8, 0), "", {}, away_days=2) is None
    assert away_return(_now(8, 0), "不是时间的东西", {}, away_days=2) is None


def test_away_refire_blocked_by_fired():
    fired = {TODAY: ["away"]}
    assert away_return(_now(8, 0), "2098-12-27T09:00:00", fired, away_days=2) is None


# ---------------- fired 记账 ----------------
def test_mark_fired_appends_without_duplication():
    fired = {}
    now = _now(8, 0)
    mark_fired(fired, now, "daily")
    mark_fired(fired, now, "daily")
    mark_fired(fired, now, "review")
    assert fired == {TODAY: ["daily", "review"]}, fired


def test_prune_fired_keeps_recent_drops_old_and_bad_keys():
    fired = {
        "2098-06-01": ["daily"],                             # 远古记录
        "2098-12-25": ["review"],                            # 恰好=今天-7天, 边界保留
        "2098-12-29": ["away"],                              # 界内保留
        TODAY: ["daily"],
        "oops": ["x"],                                       # 无法解析的脏键
    }
    prune_fired(fired, today=_now(8, 0).date(), keep_days=7)
    assert set(fired.keys()) == {"2098-12-25", "2098-12-29", TODAY}, fired


# ---------------- run_checks 编排(注入 loader, 不碰真实文件) ----------------
def test_run_checks_morning_returns_daily_only_and_persists_fired():
    tmp = tempfile.mkdtemp()
    try:
        tasks = lambda d: _state([True, False])              # 注入: 今有 1 条未完成
        cards = lambda d, today: [{"concept": "MCP", "status": "新学"}]
        msgs = run_checks(tmp, now=_now(9, 0), load_tasks_fn=tasks,
                          load_cards_fn=cards, last_open_ts="2098-12-31T22:00:00")
        assert [m["key"] for m in msgs] == ["daily"], msgs   # 早晨只该弹每日首开
        sfile = os.path.join(tmp, "settings.json")
        assert os.path.exists(sfile), "命中提醒必须落盘防重弹"
        with open(sfile, encoding="utf-8-sig") as f:
            saved = json.load(f)
        assert "daily" in saved["reminders"]["fired"][TODAY], saved
        msgs2 = run_checks(tmp, now=_now(9, 5), load_tasks_fn=tasks,
                           load_cards_fn=cards, last_open_ts="2098-12-31T22:00:00")
        assert msgs2 == [], "同日第二次不得重弹(fired 已持久化)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_checks_evening_also_triggers_review():
    tmp = tempfile.mkdtemp()
    try:
        tasks = lambda d: {"days": {}}                       # 无任务
        cards = lambda d, today: [{"concept": "RAG", "status": "需复习"}]
        msgs = run_checks(tmp, now=_now(19, 40),
                          load_tasks_fn=tasks, load_cards_fn=cards,
                          last_open_ts="2098-12-31T22:00:00")
        keys = sorted(m["key"] for m in msgs)
        # daily: 今日无任务桶但有需复习知识点 -> 概览照弹(规格: 任务或复习任一命中);
        # review: 19:40 已进 20:00 前30分钟窗口
        assert keys == ["daily", "review"], msgs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_checks_respects_master_switches():
    tmp = tempfile.mkdtemp()
    try:
        from settings import default_settings, save_settings
        cfg = default_settings()
        cfg["reminders"]["daily_first_open"] = False
        cfg["reminders"]["review_near"] = False
        cfg["reminders"]["away_nudge"] = False
        save_settings(tmp, cfg)
        tasks = lambda d: _state([False])
        cards = lambda d, today: [{"concept": "RAG", "status": "需复习"}]
        msgs = run_checks(tmp, now=_now(19, 40),
                          load_tasks_fn=tasks, load_cards_fn=cards,
                          last_open_ts="2098-12-27T09:00:00")
        assert msgs == [], "三个开关全关时应保持安静"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_checks_empty_dir_never_crashes_nor_creates_files():
    tmp = tempfile.mkdtemp()
    try:
        msgs = run_checks(tmp, now=_now(9, 0))               # 全默认loader+空目录
        assert msgs == [], msgs
        assert not os.path.exists(os.path.join(tmp, "tasks.json"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_checks_uses_preopen_snapshot_for_away():
    """契约: resident 必须在更新 last_open_ts 之前抓快照传进来, 否则回归提醒永远失灵"""
    tmp = tempfile.mkdtemp()
    try:
        tasks = lambda d: {"days": {}}
        cards = lambda d, today: []
        stale = "2098-12-28T09:00:00"                        # 4 天前的旧值
        msgs = run_checks(tmp, now=_now(9, 0), load_tasks_fn=tasks,
                          load_cards_fn=cards, last_open_ts=stale)
        assert any(m["key"] == "away" for m in msgs), msgs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tasks_json_with_bom_still_read_by_default_loader():
    """记事本改过 tasks.json(带 BOM) -> 默认 loader 必须照常读到, 不得静默当空壳"""
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "tasks.json"), "w", encoding="utf-8-sig") as f:
            f.write(json.dumps({"days": {TODAY: [{"id": "t1", "text": "BOM 冒烟任务", "done": False}]}}))
        msgs = run_checks(tmp, now=_now(9, 0))
        assert any(m["key"] == "daily" and "BOM 冒烟任务" in m["body"] for m in msgs), msgs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
