# -*- coding: utf-8 -*-
"""analyzer_llm_test.py —— analyzer v1.0 可选 LLM 语义增强测试

覆盖: 无 Key 零行为变化 / LLM 成功替换概念 / 失败熔断回退 / 坏 JSON 回退 /
      熔断后跳过后续调用 / _extract_json 容错。全部 mock 注入, 不触真实 API。
"""
import os
import json
import tempfile
import shutil
import unittest.mock as _mock


def _make_note(tmp):
    daily = os.path.join(tmp, "daily")
    os.makedirs(daily, exist_ok=True)
    p = os.path.join(daily, "2099-01-01.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 标题测试\n"
                "tags: mcp\n"
                "FastMCP 让 MCP Server 的开发变得简单, FastMCP 是真的简洁 FastMCP 简洁\n")
    return p


def _reset_fuse():
    import analyzer
    analyzer._LLM_DISABLED = False


def test_no_key_keeps_frequency_concepts():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        with _mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            rec = analyzer.analyze_note(p, learning_dir=tmp)
        joined = " ".join(rec["concepts"]).lower()
        assert rec["concepts"], rec
        assert "fastmcp" in joined or "mcp" in joined, rec
        assert "summary" not in rec, rec          # 无 Key 不产生 summary, 结构零变化
        assert sorted(rec.keys()) == ["code_langs", "concepts", "date", "tags", "topic"], rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_llm_success_replaces_concepts_and_adds_summary():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        fake = '{"concepts": ["MCP 架构", "智能体开发", "工具调用"], "summary": "MCP 与智能体开发要点"}'
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", return_value=fake) as m:
                rec = analyzer.analyze_note(p, learning_dir=tmp)
        assert m.call_count == 1, m.call_count
        assert rec["concepts"] == ["MCP 架构", "智能体开发", "工具调用"], rec
        assert rec["summary"] == "MCP 与智能体开发要点", rec
        assert rec["tags"] == ["mcp"], rec                # 非 concepts 字段不受影响
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_llm_failure_falls_back_and_fuses():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", side_effect=RuntimeError("boom")):
                rec = analyzer.analyze_note(p, learning_dir=tmp)
        joined = " ".join(rec["concepts"]).lower()
        assert "fastmcp" in joined or "mcp" in joined, rec      # 回退词频
        assert analyzer._LLM_DISABLED is True, "失败后应置熔断"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_llm_bad_json_falls_back():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", return_value="not json at all"):
                rec = analyzer.analyze_note(p, learning_dir=tmp)
        joined = " ".join(rec["concepts"]).lower()
        assert "fastmcp" in joined or "mcp" in joined, rec
        assert "summary" not in rec, rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_llm_disabled_skips_second_call():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        # 第一次失败 -> 熔断
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", side_effect=RuntimeError("boom")):
                analyzer.analyze_note(p, learning_dir=tmp)
        # 第二次(即使 mock 已恢复成功) 不再调用
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek",
                             return_value='{"concepts": ["A"], "summary": "S"}') as m:
                rec = analyzer.analyze_note(p, learning_dir=tmp)
        assert m.call_count == 0, "熔断后不应再调用 LLM"
        joined = " ".join(rec["concepts"]).lower()
        assert "fastmcp" in joined or "mcp" in joined, rec    # 保持词频
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extract_json_tolerates_markdown_fence_and_noise():
    import analyzer
    # 围栏包裹 + 前后缀噪声
    fenced = '```json\n{"concepts": ["甲", "乙"], "summary": "摘要"}\n```'
    obj = analyzer._extract_json(fenced)
    assert obj == {"concepts": ["甲", "乙"], "summary": "摘要"}, obj
    # 纯文本无 JSON
    assert analyzer._extract_json("抱歉, 我无法提供") is None
    # 空输入
    assert analyzer._extract_json("") is None
    # 坏 JSON 但有大括号
    assert analyzer._extract_json("{oops}") is None


def test_llm_concepts_rejects_noise_and_overlong():
    import analyzer
    tmp = tempfile.mkdtemp()
    _reset_fuse()
    try:
        p = _make_note(tmp)
        # 用 json.dumps 构造, 保证超长/单字/空/停用词均为真实内容而非字面文本
        fake = json.dumps({"concepts": ["好" * 60, "x", "", "  真实概念  ", "学习",
                                        "重复" * 50],
                           "summary": "  有效摘要  "}, ensure_ascii=False)
        with _mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            with _mock.patch("analyzer._call_deepseek", return_value=fake):
                rec = analyzer.analyze_note(p, learning_dir=tmp)
        # 超长/单字/空/停用词被过滤, 有效项保留并 trim
        assert rec["concepts"] == ["真实概念"], rec
        assert rec["summary"] == "有效摘要", rec
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
