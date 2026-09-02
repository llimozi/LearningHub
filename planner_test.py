# -*- coding: utf-8 -*-
"""planner_test.py —— planner 单元测试
跑法A: pytest planner_test.py      跑法B: python planner_test.py (零依赖runner)
覆盖: 疲劳触发/解除、优先级过滤、预测边界值、history裁剪、stats连击
"""
import datetime
from planner import (append_history, get_stats, detect_fatigue, is_fatigued,
                     normalize_priorities, sort_for_defer, fatigue_split,
                     lin_slope, predict_tomorrow, finalize_day)

def d(offset):
    return (datetime.date(2099, 1, 1) + datetime.timedelta(days=offset)).isoformat()

def mk_history(rates, start_total=3):
    return [{"date": d(i), "total": start_total, "done": int(round(r * start_total)), "rate": r}
            for i, r in enumerate(rates)]

def test_fatigue_trigger_after_3_low_days():
    st = {"history": mk_history([0.33, 0.0, 0.33])}
    f = detect_fatigue(st)
    assert f["active"] is True and f["since"] == d(2), f

def test_fatigue_not_triggered_mid_band_breaks_run():
    st = {"history": mk_history([0.33, 0.6, 0.33, 0.33])}  # 0.6 打断连击
    f = detect_fatigue(st)
    assert f["active"] is False, f

def test_fatigue_release_on_high_day():
    st = {"history": mk_history([0.33, 0.33, 0.33, 0.9])}  # 触发后被0.9解除
    f = detect_fatigue(st)
    assert f["active"] is False, f

def test_priority_default_fill():
    st = {"days": {"2099-01-01": [{"id": "a"}, {"id": "b", "priority": 3}]}}
    n = normalize_priorities(st)
    assert n == 1 and st["days"]["2099-01-01"][0]["priority"] == 2, st

def test_fatigue_split_moves_only_p1():
    undone = [{"id": "p1", "priority": 1}, {"id": "p2", "priority": 2}, {"id": "p3", "priority": 3}]
    s = fatigue_split(undone, True)
    assert [t["id"] for t in s["move"]] == ["p1"], s
    assert [t["id"] for t in s["defer2"]] == ["p2"], s
    assert [t["id"] for t in s["drop"]] == ["p3"], s
    s2 = fatigue_split(undone, False)
    assert len(s2["move"]) == 3 and not s2["defer2"] and not s2["drop"], s2

def test_sort_for_defer_stable_high_first():
    out = sort_for_defer([{"id": "x", "priority": 3}, {"id": "y", "priority": 1}, {"id": "z", "priority": 2}])
    assert [t["id"] for t in out] == ["y", "z", "x"], out

def test_predict_slope_boundary_legit_max():
    # 数学边界: rate∈[0,1] 且 n=7 时 LSQ 斜率上限≈3/14≈0.214, 永远到不了±0.3 → 不应误判clamped
    st = {"history": mk_history([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]), "fatigue": {"active": False}}
    p = predict_tomorrow(st)
    assert abs(p["slope"] - 0.214) < 0.001 and p["clamped"] is False, p
    assert p["predicted"] == max(1, round(p["avg7_done"] * (1 + p["slope"]))), p

def test_predict_clamp_dirty_data():
    # 脏数据(rate=2.0 持续3天) → LSQ斜率=6*2/28≈0.429>0.3 → 钳制必须生效并压到0.3
    st = {"history": mk_history([0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0]), "fatigue": {"active": False}}
    p = predict_tomorrow(st)
    assert p["clamped"] is True and abs(p["slope"] - 0.3) < 1e-9, p

def test_predict_empty_history_defaults_3():
    p = predict_tomorrow({"history": []})
    assert p["predicted"] == 3 and p["slope"] == 0.0, p

def test_predict_fatigue_cap():
    # 3高日后连续4天低完成 → 疲劳激活; avg7_done=46/7≈6.57 → cap=max(3,round(5.26))=5, 预测7被压到5
    st = {"history": mk_history([1.0, 1.0, 1.0, 0.4, 0.4, 0.4, 0.4], start_total=10)}
    assert is_fatigued(st) is True
    p = predict_tomorrow(st)
    assert p["cap"] == 5 and p["predicted"] == 5 and "上限" in p["note"], p

def test_history_trim_to_30():
    st = {"history": []}
    for i in range(35):
        append_history(st, d(i), 3, 2)
    assert len(st["history"]) == 30 and st["history"][0]["date"] == d(5), len(st["history"])

def test_stats_max_streak():
    st = {"history": mk_history([0.9, 0.2, 0.9, 0.9, 0.1, 0.85])}
    s = get_stats(st)
    assert s["max_streak"] == 2, s

def test_finalize_day_writes_history():
    st = {"days": {"2099-01-01": [{"done": True}, {"done": False}]}, "history": []}
    out = finalize_day(st, "2099-01-01")
    assert out["history"]["total"] == 2 and out["history"]["done"] == 1, out
    assert len(st["history"]) == 1, st

def test_analyzer_and_review_states():
    import os, tempfile, shutil, datetime
    import analyzer
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        with open(os.path.join(daily, "2099-01-01.md"), "w", encoding="utf-8") as f:
            f.write("# MCP 协议入门\ntags: mcp\n\"\"\"python 占位\nprint('hi')\n\"\"\"\nMCP 协议把工具调用标准化, MCP 很重要")
        data, added = analyzer.update_analysis(tmp)
        assert added == ["2099-01-01"], added
        rec = data["notes"]["2099-01-01"]
        assert rec["topic"] == "MCP 协议入门" and "mcp" in rec["tags"], rec
        # 复习状态机: gap<=1 新学 / gap>=3 需复习
        cards = analyzer.get_review_cards(tmp, today=datetime.date(2099, 1, 2))
        assert all(c["status"] == "新学" for c in cards), cards
        cards = analyzer.get_review_cards(tmp, today=datetime.date(2099, 1, 4))
        assert cards and all(c["status"] == "需复习" for c in cards), cards
        assert all(c["source_file"] == "2099-01-01.md" for c in cards), cards
        # 再次分析同日不重复追加(按日期去重)
        data2, added2 = analyzer.update_analysis(tmp)
        assert added2 == [] and len(data2["notes"]) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_graph_build_cooccurrence_and_persistence():
    import os, tempfile, shutil, json
    import graph as knowledge_graph
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        ana = {"notes": {
            "2099-01-01": {"topic": "A", "concepts": ["mcp", "fastmcp"], "tags": [], "code_langs": []},
            "2099-01-02": {"topic": "B", "concepts": ["mcp", "rag"], "tags": [], "code_langs": []}}}
        with open(os.path.join(daily, "analysis.json"), "w", encoding="utf-8-sig") as f:
            json.dump(ana, f, ensure_ascii=False)
        g = knowledge_graph.build_graph(tmp, save=True)
        assert {n["id"] for n in g["nodes"]} == {"mcp", "fastmcp", "rag"}
        mcp = [n for n in g["nodes"] if n["id"] == "mcp"][0]
        assert mcp["count"] == 2 and mcp["dates"] == ["2099-01-01", "2099-01-02"]
        ef = [e for e in g["edges"] if {e["source"], e["target"]} == {"mcp", "fastmcp"}]
        assert len(ef) == 1 and ef[0]["weight"] == 1
        # 第三天再次共现 -> 权重累加
        ana["notes"]["2099-01-03"] = {"topic": "C", "concepts": ["fastmcp", "mcp"], "tags": [], "code_langs": []}
        with open(os.path.join(daily, "analysis.json"), "w", encoding="utf-8-sig") as f:
            json.dump(ana, f, ensure_ascii=False)
        g2 = knowledge_graph.build_graph(tmp)
        e2 = [e for e in g2["edges"] if {e["source"], e["target"]} == {"mcp", "fastmcp"}][0]
        assert e2["weight"] == 2, e2
        assert g2["summary"]["total_concepts"] == 3 and g2["summary"]["core"] == "mcp"
        lg = knowledge_graph.load_graph(tmp)                       # 落盘可回读
        assert lg is not None and len(lg["nodes"]) == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_analyzer_noise_eradicated():
    import os, tempfile, shutil
    import analyzer
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        noisy = ("# ## 标题测试\ntags: mcp\n---\n***\n> 引用一行\n"
                 + "- 列表项甲\n- 列表项乙\n"
                 + "a b c 1 2 3 42\n"
                 + "FastMCP 让 MCP Server 的开发变得简单, FastMCP 是真的简洁")
        with open(os.path.join(daily, "2099-01-01.md"), "w", encoding="utf-8") as f:
            f.write(noisy)
        rec = analyzer.analyze_note(os.path.join(daily, "2099-01-01.md"), learning_dir=tmp)
        assert rec["concepts"], rec
        bad = [c for c in rec["concepts"]
               if len(c) <= 1 or c.isdigit()
               or set(c) <= set("#-*>=/\\ ")]
        assert bad == [], (rec, bad)
        joined = " ".join(rec["concepts"])
        assert ("fastmcp" in joined) or ("mcp" in joined), rec
        assert "##" not in rec["concepts"] and "---" not in rec["concepts"], rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_graph_scan_delegates_clean_concepts():
    import os, tempfile, shutil, json
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        ana = {"notes": {"2099-01-01": {"topic": "t", "concepts": ["##", "---", "fastmcp"], "tags": [], "code_langs": []}}}
        with open(os.path.join(daily, "analysis.json"), "w", encoding="utf-8-sig") as f:
            json.dump(ana, f, ensure_ascii=False)
        import graph as kg
        g = kg.build_graph(tmp, save=True)     # v0.9 起 graph 不再自带过滤——脏数据原样进图(职责已回归 analyzer)
        ids = {n["id"] for n in g["nodes"]}
        assert "fastmcp" in ids and "##" in ids   # 证明临时过滤确已移除
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_analyzer_noise_eradicated():
    import os, tempfile, shutil
    import analyzer
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        BS = chr(92)
        fence = analyzer.FENCE
        noisy = ("# ## 标题测试" + chr(10)
                 + "tags: mcp" + chr(10)
                 + "---" + chr(10) + "***" + chr(10) + "> 引用一行" + chr(10)
                 + "- 列表项甲" + chr(10) + "- 列表项乙" + chr(10)
                 + "a b c 1 2 3 42" + chr(10)
                 + fence + "python" + chr(10) + "print('hi')" + chr(10) + fence + chr(10)
                 + "FastMCP 让 MCP Server 的开发变得简单, FastMCP 是真的简洁, "
                 + "![img](x.png) 与 [链接](http://x) 不应产生噪声 token " + BS + "n 也不应出现")
        with open(os.path.join(daily, "2099-01-01.md"), "w", encoding="utf-8") as f:
            f.write(noisy)
        rec = analyzer.analyze_note(os.path.join(daily, "2099-01-01.md"), learning_dir=tmp)
        assert rec["concepts"], rec
        bad = [c for c in rec["concepts"]
               if len(c) < 2 or c.isdigit()
               or c.startswith("#") or c.startswith("-") or c.startswith("*")
               or c in ("##", "###", "---", "***", ">", "-", "*", "a", "b", "c", "42", BS + "n")]
        assert bad == [], (rec["concepts"], bad)
        joined = " ".join(rec["concepts"])
        assert "fastmcp" in joined or "mcp" in joined.lower(), rec
        assert "python" in rec["code_langs"], rec          # 围栏语言仍被识别
        assert "mcp" in rec["tags"], rec                   # tags 仍被识别
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_graph_delegation_is_unfiltered():
    import os, tempfile, shutil, json
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        ana = {"notes": {"2099-01-01": {"topic": "t", "concepts": ["##", "fastmcp"], "tags": [], "code_langs": []}}}
        with open(os.path.join(daily, "analysis.json"), "w", encoding="utf-8-sig") as f:
            json.dump(ana, f, ensure_ascii=False)
        import graph as kg
        g = kg.build_graph(tmp, save=True)     # v0.9 起 graph 不过滤——脏数据原样进图(职责已回归 analyzer)
        ids = {n["id"] for n in g["nodes"]}
        assert ids == {"##", "fastmcp"}            # 证明临时过滤确已移除
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_recommender_three_rules():
    import os, tempfile, shutil, json, datetime
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        today = datetime.date.today()
        def ds(off):
            return (today - datetime.timedelta(days=off)).isoformat()
        ana = {"notes": {
            ds(5): {"topic": "A", "concepts": ["core", "lonely"], "tags": [], "code_langs": []},
            ds(9): {"topic": "B", "concepts": ["core", "friend"], "tags": [], "code_langs": []}}}
        with open(os.path.join(daily, "analysis.json"), "w", encoding="utf-8-sig") as f:
            json.dump(ana, f, ensure_ascii=False)
        gd = {"nodes": [
                {"id": "core", "count": 2, "dates": [ds(9), ds(5)], "degree": 2},
                {"id": "friend", "count": 1, "dates": [ds(9)], "degree": 1},
                {"id": "lonely", "count": 1, "dates": [ds(5)], "degree": 0}],
              "edges": [{"source": "core", "target": "friend", "weight": 1}],
              "summary": {"total_concepts": 3, "total_edges": 1, "core": "core"}}
        with open(os.path.join(daily, "graph.json"), "w", encoding="utf-8-sig") as f:
            json.dump(gd, f, ensure_ascii=False)
        tasks = {"history": [
                    {"date": ds(6), "total": 3, "done": 3, "rate": 1.0},
                    {"date": ds(5), "total": 3, "done": 3, "rate": 1.0},
                    {"date": ds(4), "total": 3, "done": 3, "rate": 1.0},
                    {"date": ds(3), "total": 3, "done": 1, "rate": 0.33},
                    {"date": ds(2), "total": 3, "done": 0, "rate": 0.0},
                    {"date": ds(1), "total": 3, "done": 0, "rate": 0.0}],
                 "fatigue": {"active": True, "since": ds(1), "reason": "t"},
                 "days": {}, "log": []}
        with open(os.path.join(tmp, "tasks.json"), "w", encoding="utf-8-sig") as f:
            json.dump(tasks, f, ensure_ascii=False)
        import recommender
        out = recommender.get_recommendations(tmp, today=today)
        assert out["state"] == "ready"
        types = [r["type"] for r in out["items"]]
        assert types[0] == "rest", out                                  # 规则2: 疲劳回落 -> 休息优先
        assert any(r["type"] == "review" and r["concept"] == "friend" for r in out["items"]), out  # 规则1: 单次出现9天->需复习
        assert any(r["type"] == "explore" and r["concept"] == "lonely" for r in out["items"]), out  # 规则3: 孤立概念
        assert all(not (r["type"] == "review" and r["concept"] == "core") for r in out["items"]), out  # core 已巩固不推荐
        assert len(out["items"]) <= 5
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_recommender_accumulating_empty():
    import os, tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "daily"))
        import recommender
        out = recommender.get_recommendations(tmp)
        assert out["state"] == "accumulating" and out["items"] == [], out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_heatmap_scan_and_payload():
    import os, tempfile, shutil, datetime
    import heatmap
    tmp = tempfile.mkdtemp()
    try:
        daily = os.path.join(tmp, "daily")
        os.makedirs(daily)
        with open(os.path.join(daily, "2099-01-01.md"), "w", encoding="utf-8") as f:
            f.write("# MCP 笔记\ntags: mcp, rag\nMCP 协议把工具调用标准化了, 这篇笔记内容足够长一些以便拿到更高的分数档位")
        with open(os.path.join(daily, "2099-01-02.md"), "w", encoding="utf-8") as f:
            f.write("# RAG 初探\n短文")
        st = {"days": {"2099-01-01": [{"done": True}, {"done": False}]}, "history": []}
        pay = heatmap.heatmap_payload(tmp, st, days=5, today=datetime.date(2099, 1, 3))
        by = {x["date"]: x for x in pay["days"]}
        assert by["2099-01-01"]["level"] >= 1 and by["2099-01-01"]["tasks"] == 2, by
        assert by["2099-01-02"]["level"] == 1 and by["2099-01-02"]["tasks"] == 0, by
        assert by["2099-01-03"]["level"] == 0, by          # 无笔记=灰
        notes = heatmap.scan_daily(tmp)
        assert notes["2099-01-01"]["tags"] == ["mcp", "rag"], notes
        assert pay["total_notes"] == 2
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
