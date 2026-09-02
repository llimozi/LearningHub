# -*- coding: utf-8 -*-
"""normalize_enable_test.py —— Phase D-D 生产启用归一化验证测试
跑法A: pytest normalize_enable_test.py   跑法B: python normalize_enable_test.py (零依赖runner)
覆盖(Phase D-D 规格):
  1 三个生产 sync 调用点均用 normalize=True(源码级)
  2 真实 analysis -> 归一化概念
  3 既有 knowledge 条目保持不变
  4 重复 sync 幂等(第二次零新增)
  5 无删除发生
  6 归一化概念进入 due_cards
  7 复习任务标签保持可读
  8 既有 Phase C 测试保持绿色(由全量套件承担)
"""
import datetime
import inspect
import os
import shutil
import tempfile

import forgetting
import normalize


def _note(topic, concepts, tags=None, langs=None):
    return {"topic": topic, "concepts": concepts,
            "tags": tags or [], "code_langs": langs or []}


def _mk_ld(notes, pre_concepts=None):
    """建临时学习目录: analysis.json + 可选预置 knowledge 旧概念(仅建档, 无复习史)"""
    import analyzer
    d = tempfile.mkdtemp(prefix="nrm_en_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    analyzer.save_analysis(d, {"notes": notes})
    if pre_concepts:
        data = {"version": 1, "knowledge": {}}
        for c in pre_concepts:
            data["knowledge"][c] = {"first_seen": "2099-01-01", "source_date": "2099-01-01",
                                    "last_review_ts": None, "review_count": 0,
                                    "ease_factor": 2.5}
        forgetting.save_knowledge(d, data)
    return d


# ---------- 1. 三个生产调用点均用 normalize=True(源码级) ----------
def test_1_production_callers_use_normalize():
    import _app.api as api
    import _app.render_data as rd
    api_src = inspect.getsource(api)
    rd_src = inspect.getsource(rd)
    # 三个生产 sync 调用点(api_due_reviews / api_retention / build_context)
    assert api_src.count("sync_from_analysis(ld, normalize=True)") == 2, \
        "api.py 应有 2 处 normalize=True"
    assert "sync_from_analysis(BASE, normalize=True)" in rd_src, \
        "render_data.py 应有 1 处 normalize=True"
    # 无残留未启用的生产调用
    assert "sync_from_analysis(ld)" not in api_src, "api.py 存在未启用的 sync 调用"
    assert "sync_from_analysis(BASE)" not in rd_src, "render_data.py 存在未启用的 sync 调用"


# ---------- 2. 真实 analysis -> 归一化概念 ----------
def test_2_real_analysis_yields_normalized_concepts():
    d = _mk_ld({"2099-01-01": _note("学习日志", ["交付", "冒烟"], tags=["mcp", "python"]),
                "2099-01-02": _note("学习日志", ["重试"], tags=["agent"])})
    forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 2), normalize=True)
    kn = forgetting.load_knowledge(d)["knowledge"]
    for c in ("mcp", "python", "agent"):
        assert c in kn, (c, sorted(kn.keys()))
    # normalize 层本身拒绝噪音(tags 干净概念在, 且重试/冒烟不因归一化新增为干净概念)
    # 注: sync 的旧词频路径仍会建档 concepts 原词(加法不替代), 故此处只验干净概念存在
    assert normalize.normalize_concepts({"tags": ["重试", "冒烟"], "concepts": []}) == [], \
        "normalize 层应拒绝语义噪声"


# ---------- 3. 既有 knowledge 条目保持不变 ----------
def test_3_existing_entries_unchanged():
    d = _mk_ld({"2099-01-01": _note("t", ["旧概念"], tags=["mcp"])},
               pre_concepts=["旧概念"])
    before = dict(forgetting.load_knowledge(d)["knowledge"]["旧概念"])
    forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 2), normalize=True)
    after = forgetting.load_knowledge(d)["knowledge"]["旧概念"]
    assert after == before, (before, after)
    assert "review_count" in after, after


# ---------- 4. 重复 sync 幂等 ----------
def test_4_repeated_sync_idempotent():
    d = _mk_ld({"2099-01-01": _note("t", [], tags=["mcp"])})
    _, a1 = forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 2), normalize=True)
    _, a2 = forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 3), normalize=True)
    assert a1 >= 1, a1
    assert a2 == 0, a2
    kn = forgetting.load_knowledge(d)["knowledge"]
    assert kn.get("mcp", {}).get("review_count", 0) == 0, "重复 sync 不应改动复习史"


# ---------- 5. 无删除发生 ----------
def test_5_no_deletion():
    d = _mk_ld({"2099-01-01": _note("t", [], tags=["mcp"])},
               pre_concepts=["旧概念", "py"])
    before = set(forgetting.load_knowledge(d)["knowledge"])
    forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 2), normalize=True)
    after = set(forgetting.load_knowledge(d)["knowledge"])
    assert before <= after, (before - after, "有概念被删除")
    assert "mcp" in after and "py" in after, after


# ---------- 6. 归一化概念进入 due_cards ----------
def test_6_normalized_concepts_reach_due_cards():
    d = _mk_ld({"2099-07-08": _note("t", [], tags=["mcp"])})
    forgetting.sync_from_analysis(d, today=datetime.date(2099, 7, 9), normalize=True)
    cards = forgetting.due_cards(d, today=datetime.date(2099, 7, 10))
    assert any(c["concept"] == "mcp" for c in cards), cards


# ---------- 7. 复习任务标签保持可读 ----------
def test_7_review_label_readable():
    import analyzer
    from _app import services
    d = _mk_ld({"2099-07-08": _note("学习日志", ["mcp"], tags=["mcp"])})
    forgetting.sync_from_analysis(d, today=datetime.date(2099, 7, 9), normalize=True)
    analysis = analyzer.load_analysis(d)
    label = services._resolve_review_topic(analysis, "mcp", "2099-07-08")
    assert label == "MCP", label
    # 完整生成路径: compose_tomorrow 产出「复习：MCP」
    st = {"days": {}}
    out = services.compose_tomorrow(st, "2099-07-09", 3,
                                    cfg={"plan": {"version": 1, "lines": [],
                                                 "priority_windows": []},
                                         "learning_dir": d, "today": "2099-07-09"})
    texts = [g["text"] for g in out["generated"]]
    assert any(t == "复习：MCP" for t in texts), texts


# ---------- 8. Phase C 测试保持绿色 ----------
def test_8_phase_c_suite_reference():
    """源码级锚点: Phase C 管线关键函数未因启用归一化而被改动"""
    from _app import services
    compose_src = inspect.getsource(services.compose_tomorrow)
    mod_src = inspect.getsource(services)
    assert "c-rev-" in compose_src, "复习源 id 前缀不应丢失"
    assert "review_concept" in compose_src, "复习元数据不应丢失"
    assert "def maybe_mark_reviewed" in mod_src, "完成反馈 helper 不应丢失"


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
