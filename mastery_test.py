# -*- coding: utf-8 -*-
"""mastery_test.py —— 知识点掌握度模型单元测试 (v1.2 · 纯标准库)
跑法A: pytest mastery_test.py      跑法B: python mastery_test.py (零依赖runner)
覆盖: 四因子合成的方向性(复习多/保持率高/笔记多->高分; 久不复习->低分红队) /
      测验正确率的可选加权 / 封顶与钳制 / 写回记忆档案的幂等 /
      compute_all 只算不写 / 重点攻克队列排序与阈值。
"""
import datetime
import json
import os
import shutil
import tempfile

from mastery import (mastery_score, compute_all, update_mastery_scores,
                     weak_concepts, WEAK_THRESHOLD)
from forgetting import sync_from_analysis, mark_reviewed

TODAY = datetime.date(2099, 7, 10)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump(obj, f, ensure_ascii=False)


def _note(topic, concepts):
    return {"topic": topic, "concepts": concepts, "tags": [], "code_langs": []}


def _dir_with(notes):
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "daily", "analysis.json"), {"notes": notes})
    sync_from_analysis(d, today=TODAY)
    return d


# ---------------- 方向性 ----------------
def test_fresh_single_note_mid_band():
    d = _dir_with({"2099-07-09": _note("A", ["新概念"])})
    try:
        kn = json.load(open(os.path.join(d, "daily", "knowledge.json"),
                            encoding="utf-8-sig"))["knowledge"]
        s = mastery_score(kn["新概念"], note_count=1, today=TODAY)
        assert 40 <= s <= 70, s                                  # 新学概念居中, 不误入红队
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_well_reviewed_multi_note_high():
    d = _dir_with({"2099-07-01": _note("A", ["老手"]),
                   "2099-07-02": _note("B", ["老手"]),
                   "2099-07-03": _note("C", ["老手"])})
    try:
        for day in (2, 3, 4, 5, 6, 7):                          # 封顶口径: 刷满 6 次
            mark_reviewed(d, "老手", quality=5,
                          now=datetime.datetime(2099, 7, day, 8, 0))
        kn = json.load(open(os.path.join(d, "daily", "knowledge.json"),
                            encoding="utf-8-sig"))["knowledge"]
        s = mastery_score(kn["老手"], note_count=3, today=TODAY)
        assert s >= 85, s
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stale_never_reviewed_lands_in_red_queue():
    d = _dir_with({"2099-06-20": _note("旧", ["荒废点"])})       # 20 天前出现且从未复习
    try:
        kn = json.load(open(os.path.join(d, "daily", "knowledge.json"),
                            encoding="utf-8-sig"))["knowledge"]
        s = mastery_score(kn["荒废点"], note_count=1, today=TODAY)
        assert s < WEAK_THRESHOLD, s                             # 自动掉进重点攻克队列
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_monotonic_in_each_factor():
    base = {"first_seen": "2099-07-08", "last_review_ts": "2099-07-09T08:00:00",
            "review_count": 2, "ease_factor": 2.5}
    s_more_reviews = mastery_score(dict(base, review_count=4), 2, TODAY)
    assert s_more_reviews >= mastery_score(base, 2, TODAY)
    s_fresher = mastery_score(dict(base, last_review_ts="2099-07-10T08:00:00"), 2, TODAY)
    assert s_fresher > mastery_score(base, 2, TODAY)
    assert mastery_score(base, 4, TODAY) > mastery_score(base, 1, TODAY)


# ---------------- 测验正确率(可选因子) ----------------
def test_quiz_accuracy_optional_and_directional():
    rec = {"first_seen": "2099-07-08", "last_review_ts": "2099-07-09T08:00:00",
           "review_count": 2, "ease_factor": 2.5}
    s_none = mastery_score(rec, 2, TODAY)
    s_good = mastery_score(dict(rec, last_quiz_accuracy=1.0), 2, TODAY)
    s_bad = mastery_score(dict(rec, last_quiz_accuracy=0.0), 2, TODAY)
    assert s_good > s_none > s_bad, (s_none, s_good, s_bad)
    assert s_good - s_none <= 10                                 # 权重上限 10 分


# ---------------- 封顶与钳制 ----------------
def test_caps_on_reviews_and_notes_and_range():
    huge = {"review_count": 99, "ease_factor": 3.0,
            "last_review_ts": "2099-07-10T00:00:00"}
    six = {"review_count": 6, "ease_factor": 3.0,
           "last_review_ts": "2099-07-10T00:00:00"}
    assert mastery_score(huge, 99, TODAY) == mastery_score(six, 5, TODAY)
    s = mastery_score(huge, 99, TODAY)
    assert 0 <= s <= 100


# ---------------- 写回与只算 ----------------
def test_update_writes_field_idempotent():
    d = _dir_with({"2099-07-01": _note("A", ["甲"]), "2099-07-05": _note("B", ["乙"])})
    try:
        scores = update_mastery_scores(d, today=TODAY)
        assert set(scores) == {"甲", "乙"}
        raw = json.load(open(os.path.join(d, "daily", "knowledge.json"),
                             encoding="utf-8-sig"))
        assert isinstance(raw["knowledge"]["甲"]["mastery_score"], int)
        before = open(os.path.join(d, "daily", "knowledge.json"),
                      encoding="utf-8-sig").read()
        scores2 = update_mastery_scores(d, today=TODAY)
        after = open(os.path.join(d, "daily", "knowledge.json"),
                     encoding="utf-8-sig").read()
        assert scores2 == scores and before == after             # 幂等: 二跑零写盘
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_compute_all_reads_without_writing():
    d = _dir_with({"2099-07-01": _note("A", ["丙"])})
    try:
        p = os.path.join(d, "daily", "knowledge.json")
        before = open(p, encoding="utf-8-sig").read()
        scores = compute_all(d, today=TODAY)
        assert scores["丙"] >= 0
        assert open(p, encoding="utf-8-sig").read() == before, "compute 不许落盘"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_missing_notes_counted_as_zero_still_scores():
    rec = {"first_seen": "2099-07-09", "last_review_ts": "2099-07-10T08:00:00",
           "review_count": 1, "ease_factor": 2.5}
    s = mastery_score(rec, 0, TODAY)                             # 台账缺失按 0 篇兜底
    assert 0 <= s <= 100


# ---------------- 重点攻克队列 ----------------
def test_weak_queue_sorted_and_thresholded():
    d = _dir_with({
        "2099-06-01": _note("old", ["荒废A", "荒废B"]),
        "2099-07-09": _note("new", ["健康新知"]),
    })
    try:
        mark_reviewed(d, "健康新知", quality=5,
                      now=datetime.datetime(2099, 7, 10, 8, 0))
        update_mastery_scores(d, today=TODAY)
        weak = weak_concepts(d, today=TODAY)
        assert all(s < WEAK_THRESHOLD for _, s in weak)
        scores = [s for _, s in weak]
        assert scores == sorted(scores)                          # 越危险越靠前
        assert any(c == "荒废A" for c, _ in weak)
        assert all(c != "健康新知" for c, _ in weak)
        top1 = weak_concepts(d, today=TODAY, top_n=1)
        assert len(top1) == 1 and top1[0][0] == weak[0][0]
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
