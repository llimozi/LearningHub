# -*- coding: utf-8 -*-
"""recommender_v12_test.py —— 路径推荐第四规则「补弱优先」单元测试 (v1.2)
跑法A: pytest recommender_v12_test.py      跑法B: python recommender_v12_test.py
覆盖: 掌握分<40 概念触发 reinforce 且排最前(仅次于健康保护的 rest) /
      同概念不与 review/explore 规则重复出现 / 理由含掌握分·间隔天数·遗忘风险% /
      链接指向最近笔记 / 无红队时不产生 reinforce(v0.9 三规则行为不变) /
      数量上限与疲劳休息的优先级。全部临时目录+固定日期。
"""
import datetime
import json
import os
import re
import shutil
import tempfile

import recommender
from forgetting import sync_from_analysis

TODAY = datetime.date(2099, 7, 19)
STALE_DAY = (TODAY - datetime.timedelta(days=25)).isoformat()
FRESH_DAY = (TODAY - datetime.timedelta(days=1)).isoformat()


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _mk_dir(notes, history=None, fatigue_active=False, do_sync=True):
    """notes: {date_str: [concepts]}; 可选构造疲劳态历史"""
    d = tempfile.mkdtemp()
    st = {"version": 3, "days": {}, "history": history or [],
          "fatigue": {"active": bool(fatigue_active),
                      "since": None, "reason": "" if not fatigue_active else "测试"},
          "log": []}
    _write(os.path.join(d, "tasks.json"), st)
    an = {"notes": {k: {"topic": k, "concepts": list(v), "tags": [], "code_langs": []}
                    for k, v in notes.items()}}
    _write(os.path.join(d, "daily", "analysis.json"), an)
    if do_sync:
        sync_from_analysis(d, today=TODAY)
    return d


def _get(d):
    return recommender.get_recommendations(d, today=TODAY)


# ---------------- 补弱规则 ----------------
def test_weak_concept_triggers_reinforce_first():
    d = _mk_dir({STALE_DAY: ["旧知识点"]})
    try:
        r = _get(d)
        assert r["items"], r
        first = r["items"][0]
        assert first["type"] == "reinforce", r
        assert first["concept"] == "旧知识点", r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_reason_has_score_gap_and_risk_percent():
    d = _mk_dir({STALE_DAY: ["旧知识点"]})
    try:
        r = _get(d)
        reason = r["items"][0]["reason"]
        m = re.search(r"掌握分 (\d+)，已 (\d+) 天未复习，遗忘风险 (\d+)%", reason)
        assert m, reason
        score, gap, risk = int(m.group(1)), int(m.group(2)), int(m.group(3))
        assert score < 40 and gap >= 20 and risk > 50, (score, gap, risk)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_link_points_to_latest_note():
    d = _mk_dir({STALE_DAY: ["旧知识点"]})
    try:
        r = _get(d)
        assert r["items"][0]["link"] == "/editor?date=" + STALE_DAY, r["items"][0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_reinforce_dedupes_against_review_and_explore():
    # 同一「旧知识点」同时满足 需复习(gap>=3) 与 孤立(count==1) -> 只允许 reinforce 一行
    d = _mk_dir({STALE_DAY: ["旧知识点"]})
    try:
        r = _get(d)
        rows = [x for x in r["items"] if x["concept"] == "旧知识点"]
        assert len(rows) == 1 and rows[0]["type"] == "reinforce", r["items"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_reinforce_capped_at_two():
    d = _mk_dir({STALE_DAY: ["甲", "乙", "丙", "丁"]})               # 4 个全红
    try:
        r = _get(d)
        n_rf = sum(1 for x in r["items"] if x["type"] == "reinforce")
        assert n_rf == 2, r                                          # 最多占两个席位
        assert len(r["items"]) <= 5
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 健康路径不受影响 ----------------
def test_healthy_dir_keeps_v09_behavior():
    d = _mk_dir({FRESH_DAY: ["新鲜概念"]}, do_sync=False)            # 不建记忆档案=老世界
    try:
        r = _get(d)
        assert all(x["type"] != "reinforce" for x in r["items"]), r
        assert r["ok"] is True                                       # 三规则照常运转
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_rest_still_beats_reinforce_when_fatigued():
    hist = []
    for back in range(5, -1, -1):                                    # 时间升序: 最老在最前
        day = TODAY - datetime.timedelta(days=back)
        rate = 1.0 if back >= 3 else 0.0                             # 老三天高, 近三天低
        hist.append({"date": day.isoformat(), "total": 2,
                     "done": int(rate * 2), "rate": rate})
    d = _mk_dir({STALE_DAY: ["旧知识点"]},
                history=hist, fatigue_active=True)
    try:
        r = _get(d)
        assert r["items"][0]["type"] == "rest", r                    # 健康保护永远第一
        rf = [x for x in r["items"] if x["type"] == "reinforce"]
        assert len(rf) == 1, r                                       # 补弱随后
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
