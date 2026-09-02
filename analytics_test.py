# -*- coding: utf-8 -*-
"""analytics_test.py —— v1.6 数据智能模块单元测试
跑法A: pytest analytics_test.py      跑法B: python analytics_test.py (零依赖runner)
覆盖:
  A 认知负荷指数: 空状态 / 轻负荷 vs 超载单调性 / 因子透明 / 确定性
  B 知识稳固度: 空档案诚实empty / 标签聚合升序 / 最薄弱标签与最弱概念 / 分布计数
  C 专注时段: 样本不足诚实collecting / 达标ready最佳窗口 / 占比计算
  缓存: 首算cached=False / 复用cached=True / 源mtime变化触发重算
  集成: toggle 勾选写入 done_at 且取消即清除(save_tasks 打桩, 不碰真实数据)
全部固定 today 注入 + 临时目录, 与真实 learning 数据零接触。
"""
import datetime
import json
import os
import shutil
import tempfile

import analytics

TODAY = datetime.date(2099, 8, 10)


def _iso(d):
    return d.isoformat()


def _mkstate(days_spec=None, hist_done=()):
    """days_spec: {offset_days或ISO字符串: [task dict 模板列表]}; hist_done: 近7天每天完成数"""
    days = {}
    for off, tasks in (days_spec or {}).items():
        key = off if isinstance(off, str) else _iso(TODAY - datetime.timedelta(days=off))
        days[key] = tasks
    return {"version": 3, "days": days,
            "history": [{"date": _iso(TODAY - datetime.timedelta(days=i)),
                         "total": 3, "done": h, "rate": h / 3.0}
                        for i, h in enumerate(hist_done)],
            "fatigue": {}, "log": []}


def _task(tid, text="任务", done=False, pri=2, done_at=None):
    t = {"id": tid, "text": text, "done": done, "priority": pri,
         "carried": False, "src_date": _iso(TODAY)}
    if done_at:
        t["done_at"] = done_at
    return t


def _mkld(tasks_state=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8-sig") as f:
        json.dump(tasks_state or {"days": {}, "history": []}, f, ensure_ascii=False)
    return d


# ---------------- A. 认知负荷指数 ----------------
def test_cli_empty_state_is_zero_and_honest():
    out = analytics.cognitive_load_index({"days": {}, "history": []}, today=TODAY)
    assert out["index"] == 0 and out["zone"] == "轻松", out


def test_cli_light_vs_overload_monotonic():
    past_clean = {i: [_task("p%d-%d" % (i, j), done=True, pri=2) for j in range(3)]
                  for i in range(1, 8)}                       # 近7天每天都清干净(容量=3)
    light = dict(past_clean)
    light[0] = [_task("L1", done=True, pri=2), _task("L2", pri=3)]
    lo = analytics.cognitive_load_index(_mkstate(light), today=TODAY)

    heavy = {i: [_task("h%d" % i, done=False, pri=2)] for i in range(1, 6)}   # 连续5天欠账
    heavy[6] = [_task("h6", done=True, pri=2)]
    heavy[7] = [_task("h7", done=True, pri=2)]
    heavy[0] = [_task("H%d" % k, done=False, pri=1) for k in range(8)]        # 今天8条P1全没动
    hi = analytics.cognitive_load_index(_mkstate(heavy), today=TODAY)

    assert lo["index"] < hi["index"], (lo, hi)
    assert hi["index"] >= 80 and hi["zone"] == "过载", hi       # 超载触发保护文案
    assert hi["factors"]["carry_streak_days"] == 5, hi["factors"]
    assert isinstance(hi["factors"]["fatigue_active"], bool)
    assert lo["index"] <= 60 and lo["zone"] in ("轻松", "适中"), lo


def test_cli_deterministic_and_clamped():
    heavy = {0: [_task("X%d" % k, done=False, pri=1) for k in range(20)]}
    a1 = analytics.cognitive_load_index(_mkstate(heavy), today=TODAY)
    a2 = analytics.cognitive_load_index(_mkstate(heavy), today=TODAY)
    assert a1 == a2 and 0 <= a1["index"] <= 100, a1


# ---------------- B. 知识稳固度 ----------------
def _ld_with_knowledge(d):
    kp = os.path.join(d, "daily", "knowledge.json")
    knowledge = {
        "python": {"first_seen": _iso(TODAY - datetime.timedelta(days=30)) + "T09:00:00",
                   "source_date": _iso(TODAY - datetime.timedelta(days=30)),
                   "review_count": 3, "ease_factor": 2.5,
                   "last_review_ts": _iso(TODAY - datetime.timedelta(days=1)) + "T09:00:00"},
        "算法": {"first_seen": _iso(TODAY - datetime.timedelta(days=20)) + "T09:00:00",
                 "source_date": _iso(TODAY - datetime.timedelta(days=20)),
                 "review_count": 0},
    }
    with open(kp, "w", encoding="utf-8-sig") as f:
        json.dump({"version": 1, "knowledge": knowledge}, f, ensure_ascii=False)
    ap = os.path.join(d, "daily", "analysis.json")
    notes = {
        _iso(TODAY - datetime.timedelta(days=30)):
            {"topic": "py 入门", "concepts": ["python"], "tags": ["python", "基础"], "code_langs": []},
        _iso(TODAY - datetime.timedelta(days=20)):
            {"topic": "算法课", "concepts": ["算法"], "tags": ["ml"], "code_langs": []},
    }
    with open(ap, "w", encoding="utf-8-sig") as f:
        json.dump({"notes": notes}, f, ensure_ascii=False)


def test_stability_empty_archive_honest():
    d = _mkld()
    try:
        out = analytics.knowledge_stability(d, today=TODAY)
        assert out["status"] == "empty" and out["overall"] is None, out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stability_tag_aggregation_sorted_by_weakest():
    d = _mkld()
    try:
        _ld_with_knowledge(d)
        out = analytics.knowledge_stability(d, today=TODAY)
        assert out["status"] == "ready", out
        assert out["rows"][0]["tag"] == "ml", out["rows"]          # 从未复习的算法→ml 最薄弱
        assert out["rows"][0]["weakest_concept"] == "算法"
        assert out["rows"][0]["avg_retention"] < 40                # 20天未复习保持率必然很低
        py_row = [r for r in out["rows"] if r["tag"] == "python"][0]
        assert py_row["n_concepts"] == 1 and py_row["avg_retention"] > out["rows"][0]["avg_retention"]
        assert out["weakest_tag"] == "ml"
        assert sum(out["dist"].values()) == len(out["rows"])
        assert min(r["avg_retention"] for r in out["rows"]) <= out["overall"] <= max(
            r["avg_retention"] for r in out["rows"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- C. 最佳专注时段 ----------------
def test_focus_collecting_when_samples_insufficient():
    st = _mkstate({0: [_task("a", done=True, done_at=_iso(TODAY) + "T10:00:00"),
                        _task("b", done=True, done_at=_iso(TODAY) + "T21:00:00")]})
    out = analytics.focus_windows(st)
    assert out["status"] == "collecting" and out["samples"] == 2 and out["buckets"] == [], out


def test_focus_ready_best_window_and_share():
    days = {}
    stamps = ([_iso(TODAY - datetime.timedelta(days=m % 5)) + "T10:%02d:00" % m for m in range(15)]
              + [_iso(TODAY - datetime.timedelta(days=m % 4)) + "T21:%02d:00" % m for m in range(10)])
    tasks = [_task("t%d" % i, done=True, done_at=s) for i, s in enumerate(stamps)]
    days[_iso(TODAY)] = tasks
    out = analytics.focus_windows(_mkstate(days))
    assert out["status"] == "ready" and out["samples"] == 25, out
    assert len(out["buckets"]) == 7                                # 七个时段全覆盖
    assert out["best_window"] == "上午 09-12" and out["best_share"] == 60, out
    by_label = {b["label"]: b["count"] for b in out["buckets"]}
    assert by_label["上午 09-12"] == 15 and by_label["夜间 20-24"] == 10


# ---------------- 缓存 ----------------
def test_cache_roundtrip_and_invalidation():
    d = _mkld()
    try:
        tp = os.path.join(d, "tasks.json")
        p1 = analytics.get_analytics(d, today=TODAY)
        assert p1["cached"] is False and os.path.exists(os.path.join(d, "analytics_cache.json"))
        p2 = analytics.get_analytics(d, today=TODAY)
        assert p2["cached"] is True                                # mtime 未变直接复用
        st = os.stat(tp)
        os.utime(tp, (st.st_atime + 10, st.st_mtime + 10))         # 源变化 → 必须重算
        p3 = analytics.get_analytics(d, today=TODAY)
        assert p3["cached"] is False
        analytics.invalidate_cache(d)
        assert not os.path.exists(os.path.join(d, "analytics_cache.json"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- A2: quality 加权稳固度 ----------------
def _ld_with_quality(d, q_good):
    """两个同参数概念: 一个复习全 5 分, 一个全 1 分(其余完全一致)"""
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    kp = os.path.join(d, "daily", "knowledge.json")
    base = {"first_seen": _iso(TODAY - datetime.timedelta(days=30)) + "T09:00:00",
            "source_date": _iso(TODAY - datetime.timedelta(days=30)),
            "review_count": 3, "ease_factor": 2.5,
            "last_review_ts": _iso(TODAY - datetime.timedelta(days=1)) + "T09:00:00"}
    knowledge = {"好的": dict(base), "差的": dict(base)}
    log = []
    for i in range(3):
        ts = (_iso(TODAY - datetime.timedelta(days=5 + i)) + "T10:00:00")
        log.append({"ts": ts, "concept": "好的", "quality": 5 if q_good else 1})
    # 差的概念也放同样日志(由 q_good 区分不了, 所以直接两份日志分别构造)
    with open(kp, "w", encoding="utf-8-sig") as f:
        json.dump({"version": 1, "knowledge": knowledge,
                   "review_log": [dict(e, concept="好的", quality=(5 if q_good else 1)) for e in log]
                   + [{"ts": _iso(TODAY - datetime.timedelta(days=2)) + "T10:00:00",
                       "concept": "差的", "quality": (4 if q_good else 0)}]}, f, ensure_ascii=False)
    ap = os.path.join(d, "daily", "analysis.json")
    notes = {_iso(TODAY - datetime.timedelta(days=30)):
             {"topic": "t", "concepts": ["好的", "差的"], "tags": ["领域"], "code_langs": []}}
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    with open(ap, "w", encoding="utf-8-sig") as f:
        json.dump({"notes": notes}, f, ensure_ascii=False)


def test_quality_weighting_separates_good_and_bad():
    d = tempfile.mkdtemp()
    try:
        _ld_with_quality(d, q_good=True)
        good = analytics.knowledge_stability(d, today=TODAY)["overall"]
        shutil.rmtree(d, ignore_errors=True)
        d = tempfile.mkdtemp()
        _ld_with_quality(d, q_good=False)
        bad = analytics.knowledge_stability(d, today=TODAY)["overall"]
        assert good > bad, (good, bad)                 # 高质量复习的总体稳固度必须更高
        assert bad <= good - 8, (good, bad)            # 且差异要显著(全5 vs 全1/0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_quality_flag_and_fields_in_drilldown():
    d = tempfile.mkdtemp()
    try:
        _ld_with_quality(d, q_good=False)              # 全差评 -> 必须打 ⚠️
        out = analytics.knowledge_stability(d, today=TODAY)
        row = out["rows"][0]
        by_name = {c["name"]: c for c in row["concepts"]}
        bad_c = by_name["差的"]
        assert bad_c["flagged"] is True and bad_c["retention"] < bad_c["retention_raw"], bad_c
        assert bad_c["quality"] == 0, bad_c            # 最近一次评分可见(钻取展示用)
        good_c = by_name["好的"]
        assert good_c["quality"] in (0, 1), good_c     # 该场景里"好的"也被塞了低分日志
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- toggle 时间戳集成 ----------------
def test_toggle_stamps_and_clears_done_at():
    import build_dashboard as bd
    import _app.data as app_data                        # Phase 2.3 适配: toggle 已迁移 services,
    orig_save = app_data.save_tasks                     # 内部经 data.save_tasks 写盘, patch 目标随之迁移
    try:
        app_data.save_tasks = lambda st: None           # 打桩: 绝不写真实数据
        st = {"days": {bd.TODAY: [_task("x1")]}, "history": []}
        ok, dn, tn = bd.toggle(st, "x1", True)
        assert ok and dn == 1 and st["days"][bd.TODAY][0].get("done_at"), st
        ok, _, _ = bd.toggle(st, "x1", False)
        assert ok and "done_at" not in st["days"][bd.TODAY][0], st
    finally:
        app_data.save_tasks = orig_save                 # 成对还原(教训#008)


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
