# -*- coding: utf-8 -*-
"""duration_test.py —— v1.8 A3 耗时解析单元测试"""
import os
import shutil
import tempfile

import duration


def test_single_formats():
    cases = {"≤45min": 45, "<=45min": 45, "约30分钟": 30, "~1h": 60,
             "1.5小时": 90, "20m": 20, "90分钟": 90, "2 h": 120,
             "大概10分钟搞定": 10}
    for text, want in cases.items():
        got = duration.parse_duration(text)
        assert got == want, (text, got, want)


def test_range_takes_midpoint():
    cases = {"45-60min": 52, "1-1.5h": 75, "20~30分钟": 25, "任务 30 至 40 分钟内": 35}
    for text, want in cases.items():
        got = duration.parse_duration(text)
        assert got == want, (text, got, want)


def test_no_false_positives_and_none():
    for text in ["第 1/56 天打卡", "2026-08-22 交付", "v0.2 三项入 BACKLOG",
                 "W5 仪表盘原型", "普通任务没有时长", "", None]:
        assert duration.parse_duration(text) is None, text


def test_badge_format():
    assert duration.format_badge(45) == "⏱45m"
    assert duration.format_badge(120) == "⏱2h"
    assert duration.format_badge(90) == "⏱1.5h"
    assert duration.format_badge(None) is None


def test_init_today_extracts_est_minutes():
    import json
    import build_dashboard as bd
    import _app.data as app_data                        # Phase 2.3 适配: init_today_from_daily 已迁移
    orig_save = app_data.save_tasks                     # services, 内部经 data.save_tasks 写盘
    d = tempfile.mkdtemp()
    try:
        app_data.save_tasks = lambda st: None           # 打桩: 不写真实 tasks.json
        md = "# 日志\n- [ ] ① 写周报（≤45min）\n- [x] ② 复习 SM-2 约30分钟\n- [ ] ③ 无时长任务"
        st = {"days": {}, "log": []}
        st2, n = bd.init_today_from_daily(st, md)
        bucket = st2["days"][bd.TODAY]
        assert n == 3 and len(bucket) == 3
        assert bucket[0]["est_minutes"] == 45, bucket[0]
        assert bucket[1]["est_minutes"] == 30, bucket[1]
        assert "est_minutes" not in bucket[2], bucket[2]   # 解析不出就不造字段(诚实)
    finally:
        app_data.save_tasks = orig_save                 # 成对还原(教训#008)
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
