# -*- coding: utf-8 -*-
"""llm_semantic_test.py —— Phase B LLM 语义纵深测试(B1 周报洞察 / B2 概念关系 / B3 难度注入)

覆盖: 无 Key 完整回退(零调用) / mock 成功注入(有 Key 追加/写回/缓存) /
      mock 失败熔断(零二次调用) / 缓存命中不重复调 API。
全部 mock 注入, 不触真实 API; 用 _mock.patch("analyzer._call_deepseek")。
"""
import os
import json
import datetime
import tempfile
import shutil
import unittest.mock as _mock

from _app import services


def _reset_fuse():
    import analyzer
    analyzer._LLM_DISABLED = False


def _mkdir_with_state(concepts=("mcp", "agent"), log_n=0):
    """临时 knowledge.json + analysis.json(概念含 summary), 可选 review_log 条数"""
    import analyzer
    import forgetting
    d = tempfile.mkdtemp()
    daily = os.path.join(d, "daily")
    os.makedirs(daily, exist_ok=True)
    kn = {}
    for c in concepts:
        kn[c] = {"first_seen": "2099-01-01", "source_date": "2099-01-01",
                 "last_review_ts": "2099-01-05T09:00:00", "review_count": 1,
                 "ease_factor": 2.5, "stability": 2.0, "difficulty": 0.3}
    notes = {}
    for c in concepts:
        notes["2099-01-01"] = {"topic": "t", "concepts": list(concepts),
                               "tags": [], "code_langs": [],
                               "summary": "%s 要点" % c}
    forgetting.save_knowledge(d, {"version": 2, "knowledge": kn, "review_log": []})
    analyzer.save_analysis(d, {"notes": notes})
    return d


def _state():
    return {"version": 3, "days": {}, "history": [
        {"date": "2099-01-0%d" % i, "total": 3, "done": 2, "rate": 0.66}
        for i in range(1, 8)], "fatigue": {"active": False}, "log": []}


# ================= B1: 周报智能摘要 =================
def test_b1_no_key_weekly_report_pure_template():
    """无 Key: weekly_report 不触 API, 输出纯模板(无 AI 洞察段)。"""
    _reset_fuse()
    d = _mkdir_with_state()
    try:
        with _mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with _mock.patch("analyzer._call_deepseek") as m:
                r = services.weekly_report(_state(), d)
        assert m.call_count == 0, "无 Key 必须零调用"
        assert r["source"] == "template"
        assert "本周洞察" not in r["markdown"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b1_key_success_appends_insight():
    """有 Key + mock 成功: 返回 deepseek source, markdown 追加「本周洞察」段。"""
    _reset_fuse()
    d = _mkdir_with_state()
    try:
        fake = '{"insight": "mcp 概念复习偏少且掌握度低于 40, 建议本周优先补; 完成率趋势平稳。"}'
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", return_value=fake) as m:
                r = services.weekly_report(_state(), d)
        assert m.call_count == 1, m.call_count
        assert r["source"] == "deepseek", r["source"]
        assert "本周洞察" in r["markdown"]
        assert "优先补" in r["markdown"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b1_key_failure_falls_back_and_fuses():
    """有 Key + mock 抛错: 回退纯模板, 且 analyzer 熔断置位(本进程后续零二次调用)。"""
    _reset_fuse()
    d = _mkdir_with_state()
    try:
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", side_effect=RuntimeError("boom")) as m:
                r1 = services.weekly_report(_state(), d)
            assert m.call_count == 1
            assert r1["source"] == "template"
            assert "本周洞察" not in r1["markdown"]
            import analyzer
            assert analyzer._LLM_DISABLED is True, "失败后应置熔断"
            # 熔断后再次调用: 零二次调用
            with _mock.patch("analyzer._call_deepseek") as m2:
                r2 = services.weekly_report(_state(), d)
            assert m2.call_count == 0, "熔断后必须零二次调用"
            assert r2["source"] == "template"
    finally:
        _reset_fuse()
        shutil.rmtree(d, ignore_errors=True)


# ================= B2: 跨概念语义关联 =================
def test_b2_no_key_returns_none():
    """无 Key: llm_concept_relations 直接 None, 零调用。"""
    _reset_fuse()
    import analyzer
    with _mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        with _mock.patch("analyzer._call_deepseek") as m:
            out = analyzer.llm_concept_relations(
                [{"a": "RAG", "b": "向量检索"}], key="")
    assert m.call_count == 0
    assert out is None


def test_b2_key_success_returns_typed_rels():
    """有 Key + mock 成功: 返回带类型的关系列表(类型白名单校验 + 概念名小写规范化)。"""
    _reset_fuse()
    import analyzer
    fake = '{"rels": [{"a": "RAG", "b": "向量检索", "type": "上位"}, {"a": "MCP", "b": "工具调用", "type": "相关"}]}'
    with _mock.patch("analyzer._call_deepseek", return_value=fake) as m:
        out = analyzer.llm_concept_relations(
            [{"a": "RAG", "b": "向量检索"}, {"a": "MCP", "b": "工具调用"}],
            key="sk-test")
    assert m.call_count == 1
    assert out == {"rels": [
        {"a": "rag", "b": "向量检索", "type": "上位"},
        {"a": "mcp", "b": "工具调用", "type": "相关"}]}


def test_b2_illegal_type_falls_to_related():
    """模型返回非法类型 -> 兜底为「相关」, 不崩。"""
    _reset_fuse()
    import analyzer
    fake = '{"rels": [{"a": "A", "b": "B", "type": "说不清"}]}'
    with _mock.patch("analyzer._call_deepseek", return_value=fake):
        out = analyzer.llm_concept_relations([{"a": "A", "b": "B"}], key="sk-test")
    assert out["rels"][0]["type"] == "相关"


def test_b2_failure_fuses_and_second_call_zero():
    """mock 抛错: 返回 None, 熔断置位, 本进程二次调用零。"""
    _reset_fuse()
    import analyzer
    with _mock.patch("analyzer._call_deepseek", side_effect=RuntimeError("boom")) as m:
        out1 = analyzer.llm_concept_relations([{"a": "A", "b": "B"}], key="sk-test")
    assert out1 is None
    assert analyzer._LLM_DISABLED is True
    with _mock.patch("analyzer._call_deepseek") as m2:
        out2 = analyzer.llm_concept_relations([{"a": "A", "b": "B"}], key="sk-test")
    assert m2.call_count == 0
    assert out2 is None
    _reset_fuse()


# ================= B3: 语义自适应调度(难度注入) =================
def test_b3_llm_difficulty_seeds_new_concept():
    """LLM 估难度(冷启动增强): 新概念建档可接受注入的 difficulty 初值,
    且后续复习仍由遗忘表现驱动(S/D 闭环不受影响)。"""
    import forgetting
    d = _mkdir_with_state(concepts=("coldstart",))
    try:
        # 模拟冷启动注入: LLM 判定该概念偏难 -> difficulty 0.6 起步
        data = forgetting.load_knowledge(d)
        rec = data["knowledge"]["coldstart"]
        rec["difficulty"] = 0.6          # B3: LLM 冷启动覆盖默认 0.3
        forgetting.save_knowledge(d, data)
        # 一次答对复习: D 应下降(0.6×0.95), S 增长
        forgetting.mark_reviewed(d, "coldstart",
                                 now=datetime.datetime(2099, 1, 10, 9, 0), quality=4)
        rec = forgetting.load_knowledge(d)["knowledge"]["coldstart"]
        assert rec["difficulty"] < 0.6, rec           # 答对略降难度
        assert rec["stability"] > 0.5, rec            # S 增长
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b3_no_key_uses_default_difficulty():
    """无 LLM(无 Key): 新概念建档 difficulty 保持默认 0.3, D 完全由遗忘表现驱动。"""
    import forgetting
    d = _mkdir_with_state(concepts=("plain",))
    try:
        data = forgetting.load_knowledge(d)
        rec = data["knowledge"]["plain"]
        assert rec["difficulty"] == forgetting.D_DEFAULT, rec   # 默认 0.3
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ================= B2 集成: graph.enrich_relations(缓存/批量/熔断) =================
def _dir_with_graph_edges():
    """构造含共现边的 analysis(两概念同篇多次) + 空缓存。"""
    import analyzer
    import forgetting
    d = tempfile.mkdtemp()
    daily = os.path.join(d, "daily")
    os.makedirs(daily, exist_ok=True)
    notes = {}
    for ds in ("2099-01-01", "2099-01-03", "2099-01-05"):
        notes[ds] = {"topic": "t", "concepts": ["RAG", "向量检索"],
                     "tags": [], "code_langs": []}
    analyzer.save_analysis(d, {"notes": notes})
    forgetting.save_knowledge(d, {"version": 2, "knowledge": {}, "review_log": []})
    return d


def test_b2_enrich_no_key_keeps_cooccurrence():
    """无 Key: enrich_relations 零调用、返回空缓存(调用方回退共现), 不落盘异常。"""
    _reset_fuse()
    import graph
    d = _dir_with_graph_edges()
    try:
        with _mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with _mock.patch("analyzer._call_deepseek") as m:
                out = graph.enrich_relations(d)
        assert m.call_count == 0
        assert out["processed"] == 0
        assert out["rels"] == {}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b2_enrich_key_success_caches_and_dedupes():
    """有 Key: 首批判定并缓存; 二次调用缓存命中零调 API(不重复)。"""
    _reset_fuse()
    import graph
    d = _dir_with_graph_edges()
    try:
        fake = '{"rels": [{"a": "RAG", "b": "向量检索", "type": "上位"}]}'
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", return_value=fake) as m:
                out1 = graph.enrich_relations(d)
            assert m.call_count == 1
            assert out1["processed"] == 1
            assert out1["rels"].get("rag||向量检索") == "上位"   # 概念名小写规范化
            # 缓存命中: 二次零调用
            with _mock.patch("analyzer._call_deepseek") as m2:
                out2 = graph.enrich_relations(d)
            assert m2.call_count == 0, "缓存命中必须零二次调用"
            assert out2["rels"].get("rag||向量检索") == "上位"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b2_enrich_batch_limit_and_fuse_stop():
    """批量限制: 单批 <=10 对; 熔断(失败)后停批保留已缓存, 零二次调用。"""
    _reset_fuse()
    import graph
    d = _dir_with_graph_edges()
    try:
        # 3 个概念 -> 3 对候选, 构造 1 对已缓存, 触发失败熔断
        import forgetting
        import analyzer
        data = forgetting.load_knowledge(d)
        data.pop("semantic_rels", None)
        # 注入三概念共现
        notes = {"2099-01-01": {"topic": "t", "concepts": ["A", "B", "C"],
                                "tags": [], "code_langs": []}}
        analyzer.save_analysis(d, {"notes": notes})
        with _mock.patch("analyzer._call_deepseek", side_effect=RuntimeError("boom")):
            out = graph.enrich_relations(d, max_pairs=3)
        assert out["processed"] == 0           # 首批即失败 -> 未落盘
        assert graph.load_semantic_rels(d) == {}
        # 熔断后二次零调用
        with _mock.patch("analyzer._call_deepseek") as m2:
            out2 = graph.enrich_relations(d, max_pairs=3)
        assert m2.call_count == 0
    finally:
        _reset_fuse()
        shutil.rmtree(d, ignore_errors=True)


def test_b2_api_graph_carries_semantic_rels():
    """/api/graph 响应附加 semantic_rels: 无缓存为空 dict(纯共现结构不破坏);
    有缓存则带出(前端可升级描线)。"""
    import graph
    d = _dir_with_graph_edges()
    try:
        # 无缓存: 空 dict(与旧版兼容)
        g = graph.build_graph(d, save=False)
        assert g.get("semantic_rels") is None
        # 手工写入缓存后模拟 _get_graph 行为
        graph._save_semantic_rels(d, {"rag||向量检索": "上位"})
        g2 = graph.build_graph(d, save=False)
        g2["semantic_rels"] = graph.load_semantic_rels(d)
        assert g2["semantic_rels"] == {"rag||向量检索": "上位"}
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import sys
    _reset_fuse()
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, repr(ex)[:200])
        except Exception as ex:
            failed += 1
            print("ERROR", fn.__name__, repr(ex)[:200])
    _reset_fuse()
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed
          else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
