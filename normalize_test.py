# -*- coding: utf-8 -*-
"""normalize_test.py —— Phase D-B 知识归一化层聚焦测试
跑法A: pytest normalize_test.py   跑法B: python normalize_test.py (零依赖runner)
覆盖(Phase D-B 规格):
  1 tags 成为归一化概念 / 2 技术短语识别 / 3 语义噪声拒绝 / 4 concept/label 分离 /
  5 稳定归一化 / 6 英文大小写等价 / 7 缺失 tags 回退 / 8 空/无效 note 安全 /
  9 现有知识不受影响(只增不毁) / 10 关闭归一化保持旧行为 /
  11 Phase C 复习任务可读标签 / 12 等价输入不产生重复概念
"""
import datetime
import os
import shutil
import tempfile

import normalize
import forgetting


def _note(topic, concepts, tags=None, langs=None):
    return {"topic": topic, "concepts": concepts,
            "tags": tags or [], "code_langs": langs or []}


# ---------- 1. tags 成为归一化概念 ----------
def test_1_tags_become_concepts():
    n = _note("t", ["交付"], tags=["mcp", "python", "agent"])
    out = normalize.normalize_concepts(n)
    keys = [o["concept"] for o in out]
    assert "mcp" in keys and "python" in keys and "agent" in keys, out
    assert "交付" not in keys, out                      # 语义噪声被拒


# ---------- 2. 技术短语识别 ----------
def test_2_tech_term_recognition():
    n = _note("Function Calling 三连问", ["交付", "冒烟"], tags=[])
    out = normalize.normalize_concepts(n)
    keys = [o["concept"] for o in out]
    assert "function calling" in keys, out
    label = {o["concept"]: o["label"] for o in out}["function calling"]
    assert label == "Function Calling", out


# ---------- 3. 语义噪声拒绝 ----------
def test_3_semantic_noise_rejected():
    n = _note("t", ["py", "md", "txt", "json", "交付", "冒烟", "周日", "回归",
                    "selftest", "##", "-", "42"], tags=[])
    out = normalize.normalize_concepts(n)
    assert out == [], out


# ---------- 4. concept / label 分离 ----------
def test_4_concept_label_separation():
    n = _note("t", [], tags=["GitHub Trending"])
    out = normalize.normalize_concepts(n)
    # tag 命中语义噪声? 否——但 vocabulary 应给出规范 label
    labels = {o["concept"]: o["label"] for o in out}
    # GitHub Trending 作为 tag 直接进入, label=原文
    assert "github trending" in labels, out
    assert labels["github trending"] == "GitHub Trending", out


# ---------- 5. 稳定归一化(去空白) ----------
def test_5_stable_normalization():
    n1 = _note("t", [], tags=["  MCP   "])
    n2 = _note("t", [], tags=["MCP"])
    a = normalize.normalize_concepts(n1)[0]["concept"]
    b = normalize.normalize_concepts(n2)[0]["concept"]
    assert a == b == "mcp", (a, b)


# ---------- 6. 英文大小写等价 ----------
def test_6_case_insensitive():
    n1 = _note("t", [], tags=["MCP"])
    n2 = _note("t", [], tags=["mcp"])
    a = normalize.normalize_concepts(n1)[0]["concept"]
    b = normalize.normalize_concepts(n2)[0]["concept"]
    assert a == b, (a, b)


# ---------- 7. 缺失 tags 回退到 concept 候选 ----------
def test_7_missing_tags_fallback():
    n = _note("t", ["向量检索"], tags=[])
    out = normalize.normalize_concepts(n)
    assert [o["concept"] for o in out] == ["向量检索"], out


# ---------- 8. 空/无效 note 安全 ----------
def test_8_invalid_note_safe():
    assert normalize.normalize_concepts(None) == []
    assert normalize.normalize_concepts("not a dict") == []
    assert normalize.normalize_concepts({}) == []
    assert normalize.normalize_concepts({"concepts": None, "tags": None}) == []


# ---------- 9. 现有知识不受影响(只增不毁) ----------
def test_9_existing_knowledge_preserved():
    d = tempfile.mkdtemp(prefix="norm_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    try:
        analysis = {"notes": {"2099-01-01": _note("t", ["旧概念"], tags=["mcp"])}}
        import analyzer
        analyzer.save_analysis(d, analysis)
        forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 1),
                                      normalize=True)
        kn = forgetting.load_knowledge(d)["knowledge"]
        assert "旧概念" in kn, kn                       # 旧概念保留
        assert "mcp" in kn, kn                           # 归一化概念新增
        # 旧概念复习史字段完整
        assert "review_count" in kn["旧概念"], kn["旧概念"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- 10. 关闭归一化保持旧行为 ----------
def test_10_normalize_off_keeps_old_behavior():
    d = tempfile.mkdtemp(prefix="norm_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    try:
        analysis = {"notes": {"2099-01-01": _note("t", ["旧概念"], tags=["mcp"])}}
        import analyzer
        analyzer.save_analysis(d, analysis)
        forgetting.sync_from_analysis(d, today=datetime.date(2099, 1, 1),
                                      normalize=False)
        kn = forgetting.load_knowledge(d)["knowledge"]
        assert "旧概念" in kn, kn
        assert "mcp" not in kn, kn                       # 关闭时 tags 不进知识
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- 11. Phase C 复习任务可读标签 ----------
def test_11_review_label_resolution():
    import _app.services as services
    analysis = {"notes": {"2099-07-08": _note("学习日志", ["mcp"], tags=["mcp"])}}
    label = services._resolve_review_topic(analysis, "mcp", "2099-07-08")
    assert label == "MCP", label                          # 归一化 label 优先于 topic


# ---------- 12. 等价输入不产生重复概念 ----------
def test_12_no_duplicate_concepts():
    n = _note("t", ["mcp", "MCP", "  mcp  "], tags=["MCP"])
    out = normalize.normalize_concepts(n)
    keys = [o["concept"] for o in out]
    assert keys.count("mcp") == 1, keys


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
