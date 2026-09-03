# -*- coding: utf-8 -*-
"""forgetting_test.py —— 遗忘曲线引擎单元测试 (v2.0 · 纯标准库)
跑法A: pytest forgetting_test.py     跑法B: python forgetting_test.py (零依赖runner)
覆盖: 从台账同步知识点档案(幂等/source_date推进/旧档不回退) /
      艾宾浩斯间隔表 1-2-4-7-15-30 与 ease 缩放 / 打分复习与 ease 钳制 /
      到期队列排序(越危险越靠前) / 记忆衰减百分比单调性。全部临时目录+固定日期。
v2.0 新增(Phase A1/A2): FSRS 双参数调度——
      FSRS 间隔反解(手推对照) / 双曲幂律保持率 / 复习驱动 S/D 更新与钳制 /
      未复习概念保持 v1 语义 / 旧 v1 记录(无 S/D)读取回退 + 首复自动升级。
"""
import datetime
import json
import os
import shutil
import tempfile

from forgetting import (INTERVALS, P_TARGET, DECAY_DEFAULT, GROWTH,
                        S_MIN, S_MAX, D_MIN, D_MAX, S0_START,
                        load_knowledge, save_knowledge,
                        sync_from_analysis, interval_days, due_cards,
                        mark_reviewed, retention_percent, decay_rows,
                        _fsrs_interval, _fsrs_retention, _has_sd,
                        _review_pairs, calibrate_decay)

TODAY = datetime.date(2099, 7, 10)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _dir_with_notes(notes):
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "daily", "analysis.json"), {"notes": notes})
    return d


def _note(topic, concepts, tags=None):
    return {"topic": topic, "concepts": concepts, "tags": tags or [], "code_langs": []}


# ---------------- 同步 ----------------
def test_sync_creates_records_with_first_and_last_seen():
    d = _dir_with_notes({
        "2099-07-01": _note("A", ["mcp", "rag"]),
        "2099-07-05": _note("B", ["mcp"]),
    })
    try:
        data, added = sync_from_analysis(d, today=TODAY)
        kn = data["knowledge"]
        assert added == 2 and set(kn) == {"mcp", "rag"}, kn
        assert kn["mcp"]["first_seen"] == "2099-07-01"          # 最早出现日
        assert kn["mcp"]["source_date"] == "2099-07-05"         # 最近笔记日(跳转用)
        assert kn["rag"]["first_seen"] == "2099-07-01"
        assert kn["mcp"]["review_count"] == 0 and kn["mcp"]["ease_factor"] == 2.5
        assert kn["mcp"]["last_review_ts"] is None              # 从未复习过
        assert _read(os.path.join(d, "daily", "knowledge.json"))["knowledge"]  # 已落盘
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sync_idempotent_and_advances_source_not_history():
    d = _dir_with_notes({"2099-07-01": _note("A", ["mcp"])})
    try:
        data1, added1 = sync_from_analysis(d, today=TODAY)
        mark_reviewed(d, "mcp", now=datetime.datetime(2099, 7, 3, 8, 0))
        data2, added2 = sync_from_analysis(d, today=TODAY)
        assert added1 == 1 and added2 == 0                      # 二次同步不重复建档
        m = data2["knowledge"]["mcp"]
        assert m["first_seen"] == "2099-07-01"
        assert m["review_count"] == 1                           # 复习史不被同步抹掉
        # 之后新笔记出现: source_date 推进, 其余不动
        _write(os.path.join(d, "daily", "analysis.json"),
               {"notes": {"2099-07-01": _note("A", ["mcp"]),
                          "2099-07-09": _note("C", ["mcp"])}})
        data3, _ = sync_from_analysis(d, today=TODAY)
        m3 = data3["knowledge"]["mcp"]
        assert m3["source_date"] == "2099-07-09" and m3["review_count"] == 1
        assert m3["first_seen"] == "2099-07-01"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sync_tolerates_missing_or_empty_analysis():
    d = tempfile.mkdtemp()
    try:
        data, added = sync_from_analysis(d, today=TODAY)
        assert added == 0 and data["knowledge"] == {}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 间隔表 ----------------
def test_interval_table_progression():
    rec = {"review_count": 0, "ease_factor": 2.5}
    seen = []
    for expect in INTERVALS:                                    # 1,2,4,7,15,30
        assert interval_days(rec) == expect, (rec, expect)
        seen.append(interval_days(rec))
        rec = dict(rec, review_count=rec["review_count"] + 1)
    assert seen == [1, 2, 4, 7, 15, 30]
    rec["review_count"] = 99                                    # 封顶不再增长
    assert interval_days(rec) == 30


def test_ease_factor_scales_interval_both_directions():
    low = {"review_count": 2, "ease_factor": 1.3}               # 掌握差: 间隔缩短
    high = {"review_count": 2, "ease_factor": 3.0}              # 掌握好: 间隔拉长
    assert interval_days(low) < interval_days({"review_count": 2, "ease_factor": 2.5})
    assert interval_days(high) > interval_days({"review_count": 2, "ease_factor": 2.5})
    assert interval_days(low) >= 1                              # 下限保底一天


# ---------------- 复习打分 ----------------
def test_mark_reviewed_updates_fields_and_rejects_unknown():
    d = _dir_with_notes({"2099-07-01": _note("A", ["mcp"])})
    try:
        sync_from_analysis(d, today=TODAY)
        ok = mark_reviewed(d, "mcp", now=datetime.datetime(2099, 7, 11, 9, 30), quality=5)
        assert ok is True
        m = load_knowledge(d)["knowledge"]["mcp"]
        assert m["review_count"] == 1
        assert m["last_review_ts"] == "2099-07-11T09:30:00"
        assert m["ease_factor"] > 2.5                            # 答得好 ease 上调
        assert mark_reviewed(d, "不存在的概念") is False          # 未建档概念拒绝
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ease_clamped_on_extreme_qualities():
    d = _dir_with_notes({"2099-07-01": _note("A", ["x"]), "2099-07-01b": _note("B", ["y"])})
    try:
        sync_from_analysis(d, today=TODAY)
        for _ in range(20):
            mark_reviewed(d, "x", quality=0, now=datetime.datetime(2099, 7, 5, 8, 0))
            mark_reviewed(d, "y", quality=5, now=datetime.datetime(2099, 7, 5, 8, 0))
        kn = load_knowledge(d)["knowledge"]
        assert kn["x"]["ease_factor"] == 1.3, kn["x"]           # 连续答砸: 钳在下限
        assert kn["y"]["ease_factor"] == 3.0                    # 连续答好: 钳在上限
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 到期与衰减 ----------------
def test_never_reviewed_due_after_first_interval():
    d = _dir_with_notes({"2099-07-10": _note("今天学的", ["fresh"]),
                         "2099-07-08": _note("前天学的", ["stale"])})
    try:
        sync_from_analysis(d, today=TODAY)
        cards = {c["concept"]: c for c in due_cards(d, today=TODAY)}
        assert "stale" in cards, "隔了2天未复习必须到期"
        assert "fresh" not in cards, "当天刚学不该立刻进复习队列(D+1 才开始)"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_due_after_effective_interval_and_overdue_flag():
    d = _dir_with_notes({"2099-07-01": _note("A", ["k"])})
    try:
        sync_from_analysis(d, today=TODAY)
        # 第一次复习于 7-03, 间隔=1天(ease 2.5) -> 7-04 应再到期
        mark_reviewed(d, "k", now=datetime.datetime(2099, 7, 3, 8, 0))
        cards = {c["concept"]: c for c in due_cards(d, today=TODAY)}   # TODAY=7-10
        c = cards["k"]
        assert c["overdue_days"] >= 5 and c["status"] == "已逾期", c
        # 刚复习完的当天不应再出现在到期队列
        mark_reviewed(d, "k", now=datetime.datetime(2099, 7, 10, 8, 0))
        assert all(x["concept"] != "k" for x in due_cards(d, today=TODAY))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_due_cards_sorted_weakest_first():
    d = _dir_with_notes({"2099-07-01": _note("A", ["aaa", "bbb"])})
    try:
        sync_from_analysis(d, today=TODAY)
        mark_reviewed(d, "aaa", quality=0, now=datetime.datetime(2099, 7, 2, 8, 0))  # ease 跌
        mark_reviewed(d, "bbb", quality=5, now=datetime.datetime(2099, 7, 2, 8, 0))
        cards = due_cards(d, today=TODAY)
        rets = [c["retention"] for c in cards]
        assert rets == sorted(rets), cards                       # 衰减最多的排最前
        assert cards[0]["concept"] == "aaa"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_retention_monotone_decreasing_with_gap():
    fresh = {"first_seen": "2099-07-10", "last_review_ts": "2099-07-10T08:00:00",
             "review_count": 1, "ease_factor": 2.5}
    r_now = retention_percent(fresh, today=TODAY)                # gap=0
    old = dict(fresh, last_review_ts="2099-06-01T08:00:00")
    r_old = retention_percent(old, today=TODAY)                  # gap 很大
    assert r_now >= 95 and r_old <= 40, (r_now, r_old)
    mid = dict(fresh, last_review_ts="2099-07-05T08:00:00")
    assert r_now > retention_percent(mid, today=TODAY) > r_old   # 单调递减


def test_decay_rows_respects_topn_and_shape():
    notes = {}
    for i in range(25):
        notes["2099-07-%02d" % (i + 1)] = _note("n%d" % i, ["c%02d" % i])
    d = _dir_with_notes(notes)
    try:
        sync_from_analysis(d, today=TODAY)
        rows = decay_rows(d, today=TODAY, top_n=20)
        assert len(rows) == 20
        assert set(rows[0].keys()) >= {"concept", "retention", "review_count", "interval"}
        rets = [r["retention"] for r in rows]
        assert rets == sorted(rets)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 存取容错 ----------------
def test_load_tolerates_missing_or_broken_file(tmpdir=None):
    d = tempfile.mkdtemp()
    broken = tempfile.mkdtemp()
    try:
        assert load_knowledge(d)["knowledge"] == {}
        os.makedirs(os.path.join(broken, "daily"))
        with open(os.path.join(broken, "daily", "knowledge.json"), "w",
                  encoding="utf-8") as f:
            f.write("{半截")
        assert load_knowledge(broken)["knowledge"] == {}         # 损坏按空档案处理
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(broken, ignore_errors=True)


def test_save_roundtrip():
    d = tempfile.mkdtemp()
    try:
        data = {"version": 1, "knowledge": {"k": {"first_seen": "2099-07-01"}}}
        save_knowledge(d, data)
        assert _read(os.path.join(d, "daily", "knowledge.json")) == data
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- v2.0 FSRS 双参数调度 (Phase A1/A2) ----------------
def test_fsrs_interval_handcalc():
    """间隔反解手推对照: interval = S×((1/0.9)^(1/0.09) − 1) ≈ S×2.2242
    验收基准(豆包手推同式): S=5→11, S=30→67, S=100→222。"""
    for s, expect in ((5, 11), (30, 67), (100, 222)):
        rec = {"stability": s, "difficulty": 0.3, "review_count": 5,
               "last_review_ts": "2099-01-01T00:00:00"}
        assert interval_days(rec) == expect, (s, interval_days(rec))


def test_fsrs_interval_monotone_and_floor():
    """S 单调不减; 下限 1 天。"""
    prev = 0
    for s in range(1, 500):
        rec = {"stability": s, "review_count": 3,
               "last_review_ts": "2099-01-01T00:00:00"}
        i = interval_days(rec)
        assert i >= prev, (s, i, prev)
        assert i >= 1
        prev = i
    assert interval_days({"stability": 0.001, "review_count": 3,
                          "last_review_ts": "2099-01-01T00:00:00"}) >= 1


def test_fsrs_retention_shape():
    """幂律保持率: gap=0 -> 100%; gap 越大越低; S 越大越抗遗忘。"""
    r0 = {"stability": 10.0, "last_review_ts": "2099-07-10T00:00:00"}
    assert retention_percent(r0, today=datetime.date(2099, 7, 10)) == 100
    r5 = retention_percent(r0, today=datetime.date(2099, 7, 15))
    r30 = retention_percent(r0, today=datetime.date(2099, 8, 9))
    assert r30 < r5 < 100, (r5, r30)
    small = {"stability": 2.0, "last_review_ts": "2099-07-10T00:00:00"}
    assert retention_percent(small, today=datetime.date(2099, 7, 15)) < r5


def test_mark_reviewed_drives_sd_both_directions():
    """答对拉长 S/略降 D; 答错砍半 S/抬 D。"""
    d = _dir_with_notes({"2099-07-01": _note("A", ["c"])})
    try:
        sync_from_analysis(d, today=TODAY)
        mark_reviewed(d, "c", now=datetime.datetime(2099, 7, 2, 9, 0), quality=5)
        good = load_knowledge(d)["knowledge"]["c"]
        assert good["stability"] == round(S0_START * GROWTH[5], 2), good
        d0 = good["difficulty"]
        mark_reviewed(d, "c", now=datetime.datetime(2099, 7, 3, 9, 0), quality=1)
        bad = load_knowledge(d)["knowledge"]["c"]
        assert bad["stability"] < good["stability"], (good, bad)
        assert bad["difficulty"] > d0, (d0, bad)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sd_clamped_on_extremes():
    """S 钳 [1,3650], D 钳 [0.1,0.95]。"""
    d = _dir_with_notes({"2099-07-01": _note("A", ["hi", "lo"])})
    try:
        sync_from_analysis(d, today=TODAY)
        for _ in range(40):
            mark_reviewed(d, "hi", quality=5,
                          now=datetime.datetime(2099, 7, 5, 8, 0))
            mark_reviewed(d, "lo", quality=0,
                          now=datetime.datetime(2099, 7, 5, 8, 0))
        kn = load_knowledge(d)["knowledge"]
        assert kn["hi"]["stability"] <= S_MAX
        assert kn["hi"]["difficulty"] >= D_MIN
        assert kn["lo"]["difficulty"] <= D_MAX
        assert kn["lo"]["stability"] >= S_MIN
        assert _has_sd(kn["hi"]) and _has_sd(kn["lo"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_v1_record_reads_back_unaffected():
    """旧 v1 数据(无 S/D): 读取/间隔/保持率与升级前完全一致(档位表+指数曲线)。"""
    d = tempfile.mkdtemp()
    try:
        old = {"version": 1, "knowledge": {
            "k1": {"first_seen": "2099-07-01", "source_date": "2099-07-01",
                   "last_review_ts": "2099-07-05T09:00:00",
                   "review_count": 1, "ease_factor": 2.5}},
            "review_log": []}
        _write(os.path.join(d, "daily", "knowledge.json"), old)
        rec = load_knowledge(d)["knowledge"]["k1"]
        assert not _has_sd(rec)
        assert interval_days(rec) == 2                    # v1 count=1 档位
        # v1 指数曲线: R=exp(-gap/稳定度), 距5天 -> exp(-5/3.2)≈21%
        r = retention_percent(rec, today=datetime.date(2099, 7, 10))
        assert 18 <= r <= 24, r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_v1_record_upgrades_on_first_review():
    """旧 v1 记录首次复习自动初始化 S/D 并升级 version=2, 行为转 FSRS。"""
    d = tempfile.mkdtemp()
    try:
        old = {"version": 1, "knowledge": {
            "k1": {"first_seen": "2099-07-01", "source_date": "2099-07-01",
                   "last_review_ts": "2099-07-05T09:00:00",
                   "review_count": 1, "ease_factor": 2.5}},
            "review_log": []}
        _write(os.path.join(d, "daily", "knowledge.json"), old)
        mark_reviewed(d, "k1", now=datetime.datetime(2099, 7, 10, 9, 0), quality=4)
        data = load_knowledge(d)
        rec = data["knowledge"]["k1"]
        assert data["version"] == 2
        assert _has_sd(rec)
        # S0 = v1 有效间隔 2 天(有复习史) -> q=4 ×2.0 -> 4.0
        assert rec["stability"] == 4.0, rec
        assert rec["difficulty"] == round(0.3 * 0.95, 2) == 0.28
        assert interval_days(rec) == _fsrs_interval(rec)  # 已转 FSRS
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_unreviewed_concept_keeps_v1_semantics():
    """未复习概念(有 stability 起步值但无 last_review_ts): interval/保持率
    保持 v1 语义(首档 1 天 + 指数曲线)——升级只影响复习过的轨迹。"""
    d = _dir_with_notes({"2099-07-01": _note("A", ["新概念"])})
    try:
        sync_from_analysis(d, today=TODAY)
        rec = load_knowledge(d)["knowledge"]["新概念"]
        assert rec["stability"] == S0_START            # v2 起步值已建档
        assert not rec.get("last_review_ts")
        assert interval_days(rec) == INTERVALS[0]      # 未复习 -> 首档 1 天
        # 距首见 25 天 -> v1 指数曲线衰减到 ~0%
        r = retention_percent(rec, today=datetime.date(2099, 7, 26))
        assert r <= 5, r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_quality_edge_values():
    """quality 边界: 0 与 5 均被正确接受且钳制; 非法值(如 9/-1)不炸。"""
    d = _dir_with_notes({"2099-07-01": _note("A", ["e"])})
    try:
        sync_from_analysis(d, today=TODAY)
        assert mark_reviewed(d, "e", quality=0,
                             now=datetime.datetime(2099, 7, 2, 8, 0)) is True
        assert mark_reviewed(d, "e", quality=5,
                             now=datetime.datetime(2099, 7, 3, 8, 0)) is True
        assert mark_reviewed(d, "e", quality=9,       # 越界 -> 钳到 5
                             now=datetime.datetime(2099, 7, 4, 8, 0)) is True
        assert mark_reviewed(d, "e", quality=-3,      # 越界 -> 钳到 0
                             now=datetime.datetime(2099, 7, 5, 8, 0)) is True
        rec = load_knowledge(d)["knowledge"]["e"]
        assert S_MIN <= rec["stability"] <= S_MAX
        assert D_MIN <= rec["difficulty"] <= D_MAX
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- v2.0 真实校准 (Phase A3) ----------------
def test_calibrate_returns_default_when_insufficient():
    """复习样本 < 30 或 log 为空 -> 静默返回默认 DECAY, 不强行拟合。"""
    d = _dir_with_notes({"2099-07-01": _note("A", ["c1"])})
    try:
        sync_from_analysis(d, today=TODAY)
        # 空 review_log
        assert calibrate_decay(d) == DECAY_DEFAULT
        # 少量(2 条)仍不足
        mark_reviewed(d, "c1", now=datetime.datetime(2099, 7, 2, 8, 0))
        mark_reviewed(d, "c1", now=datetime.datetime(2099, 7, 5, 8, 0))
        assert calibrate_decay(d) == DECAY_DEFAULT
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_calibrate_sufficient_data_in_range():
    """充足配对复习样本 -> 输出有值且 ∈ [DECAY_MIN, DECAY_MAX]。"""
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "daily"), exist_ok=True)
        log = []
        kn = {}
        for ci in range(8):
            c = "concept%d" % ci
            kn[c] = {"first_seen": "2099-01-01", "source_date": "2099-01-01",
                     "last_review_ts": "2099-02-01T09:00:00", "review_count": 7,
                     "ease_factor": 2.5, "stability": 10.0, "difficulty": 0.3}
            base = datetime.datetime(2099, 1, 1, 9, 0)
            for r in range(7):
                ts = (base + datetime.timedelta(days=5 * (r + 1))).isoformat(timespec="seconds")
                log.append({"ts": ts, "concept": c, "quality": 4})
        save_knowledge(d, {"version": 2, "knowledge": kn, "review_log": log})
        samples = _review_pairs(d)
        assert len(samples) >= 30, len(samples)
        out = calibrate_decay(d)
        assert out is not None
        assert 0.05 <= out <= 0.50, out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_calibrate_silent_on_broken_data():
    """损坏数据(非 dict log) -> 静默返回默认, 不抛。"""
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "daily"), exist_ok=True)
        save_knowledge(d, {"version": 2, "knowledge": {}, "review_log": "损坏"})
        assert calibrate_decay(d) == DECAY_DEFAULT
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ensure_reports_hook_runs_calibration_without_breaking():
    """reportio.ensure_reports 挂载校准: 正常生成报告且不抛错(每周低频钩子)。"""
    import reportio
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "daily"), exist_ok=True)
        r = reportio.ensure_reports(d, today=TODAY)
        assert isinstance(r, dict) and "created" in r          # 报告流程未破坏
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
