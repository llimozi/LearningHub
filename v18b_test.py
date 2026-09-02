# -*- coding: utf-8 -*-
"""v18b_test.py —— v1.8 阶段二: B1 排期 / B2 叙事周报 / B3 今日焦点 单元测试"""
import datetime
import json
import os
import shutil
import tempfile

import analytics
import build_dashboard as bd
import _app.config as app_config          # Phase 2.2 适配: 隔离 patch 目标从 bd.* 迁至 _app.config.*

TODAY = datetime.date(2099, 8, 10)          # 周三

def _iso(d):
    return d.isoformat()

def _task(tid, text="t", done=False, pri=2, est=None, done_at=None):
    t = {"id": tid, "text": text, "done": done, "priority": pri,
         "carried": False, "src_date": _iso(TODAY)}
    if est:
        t["est_minutes"] = est
    if done_at:
        t["done_at"] = done_at
    return t

def _mkstate(days):
    return {"version": 3, "days": days, "history": [], "fatigue": {}, "log": []}


# ---------------- B1: suggest_slot ----------------
def test_slot_collecting_degrades_without_focus_source():
    st = _mkstate({0: [_task("a", done=True)]})            # 无 done_at -> focus collecting
    out = analytics.suggest_slot(st, priority=2, today=TODAY)
    assert "focus" not in out["sources"], out
    assert out["confidence"] in ("mid", "low"), out
    assert out["suggested_day"] in [_iso(TODAY + datetime.timedelta(days=i)) for i in range(3)]


def test_slot_ready_picks_lowest_load_day():
    days = {}
    for i in range(25):                                     # 25 个带时刻完成 -> focus ready
        d = TODAY - datetime.timedelta(days=i % 7 + 1)
        days.setdefault(_iso(d), []).append(
            _task("h%d" % i, done=True, done_at=_iso(d) + "T10:%02d:00" % (i % 60)))
    days[_iso(TODAY)] = [_task("t%d" % k, pri=1, est=90) for k in range(4)]   # 今天重载
    days[_iso(TODAY + datetime.timedelta(days=1))] = [_task("m0", pri=2, est=60) for k in range(3)]  # 明天中载
    days[_iso(TODAY + datetime.timedelta(days=2))] = [_task("f0", pri=3, est=15)]  # 后天最轻
    out = analytics.suggest_slot(_mkstate(days), priority=2, est_minutes=30, today=TODAY)
    assert "focus" in out["sources"] and out["confidence"] == "mid", out
    assert out["suggested_day"] == _iso(TODAY + datetime.timedelta(days=2)), out


def test_slot_weakness_alert_when_tag_hits():
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "daily"))
        with open(os.path.join(d, "daily", "knowledge.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "knowledge": {
                "算法": {"first_seen": _iso(TODAY - datetime.timedelta(days=20)) + "T09:00:00",
                          "review_count": 0}}}, f, ensure_ascii=False)
        with open(os.path.join(d, "daily", "analysis.json"), "w", encoding="utf-8") as f:
            json.dump({"notes": {_iso(TODAY - datetime.timedelta(days=20)):
                       {"topic": "t", "concepts": ["算法"], "tags": ["ml"], "code_langs": []}}},
                      f, ensure_ascii=False)
        out = analytics.suggest_slot(_mkstate({}), priority=2, tag="ml",
                                     today=TODAY, learning_dir=d)
        assert out["weakness_alert"] is True and "stability" in out["sources"], out
        assert "ml" in out["reason"], out
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- B2: narrative ----------------
def test_narrative_collecting_when_no_data():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8") as f:
            json.dump({"days": {}, "history": []}, f)
        out = analytics.generate_weekly_narrative(d, today=TODAY)
        assert out["status"] == "collecting" and "积累" in out["message"], out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_narrative_ready_with_rules():
    d = tempfile.mkdtemp()
    try:
        sat = datetime.date(2099, 7, 25)                            # 周六: 本周已过6天
        days = {}
        monday = sat - datetime.timedelta(days=sat.weekday())
        for i in range(6):                                          # 周一到周六全清
            dd = monday + datetime.timedelta(days=i)
            days[_iso(dd)] = [_task("d%d-%d" % (i, j), done=True, est=30) for j in range(3)]
        with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8") as f:
            json.dump(_mkstate(days), f, ensure_ascii=False)
        out = analytics.generate_weekly_narrative(d, today=sat)
        assert out["status"] == "ready", out
        assert out["stats"]["full_days"] == 6, out["stats"]
        assert out["stats"]["completion_rate"] == 100, out["stats"]
        assert any("全" in h for h in out["highlights"]), out["highlights"]
        md_like = out["headline"] + out["next_week_suggestion"]
        assert len(md_like) > 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- B3: daily_focus 五级场景(打桩 BASE, 不碰真实数据) ----------------
def _focus_with(tasks=None, meta=None):
    d = tempfile.mkdtemp()
    st = {"days": {bd.TODAY: tasks or []}, "history": [],
          "fatigue": {}, "log": [], "meta": meta or {}}
    with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    old_base, old_tf = app_config.BASE, app_config.TASKS_FILE   # load_tasks 走 TASKS_FILE,
    app_config.BASE, app_config.TASKS_FILE = d, os.path.join(d, "tasks.json")   # get_analytics/due_cards 走 BASE
    return d, (old_base, old_tf)


def test_focus_fatigue_mode_first():
    d, old = _focus_with([_task("p1", pri=1)],
                         meta={"fatigue_override": {"active": True, "date": bd.TODAY}})
    try:
        out = bd.api_daily_focus()
        assert "减负" in out["text"] and out["urgency"] == "mid", out
    finally:
        app_config.BASE, app_config.TASKS_FILE = old
        shutil.rmtree(d, ignore_errors=True)


def test_focus_p1_task_next():
    d, old = _focus_with([_task("a", pri=2, done=True), _task("b", pri=1, est=45)])
    try:
        out = bd.api_daily_focus()
        assert "攻克" in out["text"] and "⏱45m" in out["text"], out
        assert out["urgency"] == "high" and out["link_hash"] == "#pnl-tasks", out
    finally:
        app_config.BASE, app_config.TASKS_FILE = old
        shutil.rmtree(d, ignore_errors=True)


def test_focus_fallback_empty_day():
    d, old = _focus_with([])
    try:
        out = bd.api_daily_focus()
        assert out["icon"] == "🌱" and out["urgency"] == "low", out
    finally:
        app_config.BASE, app_config.TASKS_FILE = old
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("PASS", name)
        except Exception as e:
            failed += 1
            print("FAIL", name, "->", repr(e)[:200])
    if failed:
        print("RUNNER: %d FAILED" % failed)
    else:
        print("RUNNER: ALL GREEN (%d tests)" % len(fns))
