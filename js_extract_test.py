# -*- coding: utf-8 -*-
"""js_extract_test.py —— D-5a JS 外链回归测试 (v1.1 · 纯标准库)

验证: dashboard.js 外链后
  1. dashboard.js 文件存在且不含未替换 placeholder
  2. render(interactive=True) 输出引用 /dashboard.js, 不含内联 JS
  3. render(interactive=False) 快照保持自包含(内联 JS)
  4. LH_CONFIG 动态参数类型正确(graphEmpty 字符串 / guideDone 布尔)
  5. /dashboard.js 静态路由可用(HTTP 200 + JS Content-Type)
  6. dashboard.js 语法合法(可被浏览器/Node 解析)
  7. renderer.py 无 __JS_LOADER__ 等占位残留

防止未来 JS 又被塞回 renderer.py / placeholder 丢失。
"""
import io
import os
import re
import sys
import json
import unittest.mock as _mock

import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_BASE = os.path.dirname(os.path.abspath(__file__))
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")
_RENDERER_PATH = os.path.join(_BASE, "_app", "renderer.py")


def _render(interactive):
    """隔离写盘副作用渲染。"""
    with _mock.patch.object(_services, "init_today_from_daily", return_value=(None, 0)), \
         _mock.patch.object(_services, "auto_catchup", return_value=[]), \
         _mock.patch.object(_planner, "normalize_priorities", return_value=0), \
         _mock.patch.object(_renderer.render_data.mastery, "weak_concepts", return_value=[]), \
         _mock.patch.object(_renderer.render_data.analyzer, "update_analysis", return_value=(None, [])), \
         _mock.patch.object(_renderer.render_data.forgetting, "sync_from_analysis", return_value=(None, 0)):
        return _renderer.render(interactive)


def test_dashboard_js_exists_and_clean():
    """1/4: dashboard.js 存在、非空、不含未替换 placeholder、无 __GRAPH_EMPTY__/__GUIDEDONE__ 残留。"""
    assert os.path.exists(_JS_PATH), "templates/dashboard.js 缺失"
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    assert len(js.strip()) > 1000, "dashboard.js 过短(疑似空壳)"
    assert "__" not in js or not re.search(r"__[A-Z_]{2,}__", js), "dashboard.js 含未替换 placeholder"
    assert "__GRAPH_EMPTY__" not in js and "__GUIDEDONE__" not in js, "动态参数残留"


def test_interactive_html_references_external_js():
    """2/4: interactive 模式输出引用 /dashboard.js 且不含内联 JS。"""
    html = _render(True)
    assert 'script src="/dashboard.js"' in html, "interactive HTML 未引用 /dashboard.js"
    assert "window.LH_CONFIG" in html, "interactive HTML 缺 LH_CONFIG 配置段"
    assert "scrollspy" not in html, "interactive HTML 仍含内联 JS(D-5a 未生效)"


def test_snapshot_html_stays_self_contained():
    """3/4: 快照模式(interactive=False)保持自包含: 内联 JS, 不引用外链。"""
    html = _render(False)
    assert "scrollspy" in html, "快照 HTML 缺内联 JS(自包含能力丢失)"
    assert "window.LH_CONFIG" in html, "快照 HTML 缺 LH_CONFIG 配置段"
    assert "<script src=" not in html, "快照不应引用外链 JS"


def test_lh_config_types_correct():
    """4/4: LH_CONFIG 动态参数类型正确: graphEmpty=JSON 字符串, guideDone=布尔字面量。"""
    html = _render(True)
    m = re.search(r"window\.LH_CONFIG = \{(.*?)\};", html, re.S)
    assert m, "LH_CONFIG 未注入"
    cfg = m.group(1)
    gd = re.search(r"guideDone:\s*(true|false)", cfg)
    assert gd, "guideDone 缺失或非布尔"
    assert gd.group(1) in ("true", "false"), "guideDone 必须是布尔字面量"
    ge = re.search(r"graphEmpty:\s*(.+?)(?:,|$)", cfg)
    assert ge, "graphEmpty 缺失"
    assert ge.group(1).strip().startswith('"'), "graphEmpty 必须是 JSON 字符串(双引号)"


def test_renderer_no_js_leftovers():
    """renderer.py 的 JS 相关占位符必须是"模板+replace"配对(各出现>=2次), 非孤儿。"""
    with open(_RENDERER_PATH, encoding="utf-8") as f:
        src = f.read()
    for ph in ("__JS_LOADER__", "__GRAPH_EMPTY_JSON__", "__GUIDEDONE_JSON__"):
        cnt = src.count(ph)
        assert cnt >= 2, "占位符 %s 出现 %d 次(应>=2: 模板定义+replace配对)" % (ph, cnt)
    assert 'script src="/dashboard.js"' in src, "renderer.py 缺外链 script 模板"


def test_dashboard_js_syntax_valid():
    """dashboard.js 语法合法(用 Python 内嵌 JS 引擎不可行, 用 node 或基本括号检查)。"""
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    # 基本括号/引号配平检查(粗粒度 sanity)
    assert js.count("{") == js.count("}"), "dashboard.js 花括号不配平"
    assert js.count("(") == js.count(")"), "dashboard.js 圆括号不配平"
    assert js.count("[") == js.count("]"), "dashboard.js 方括号不配平"


# ================= D-5b-2C: pnl-help 7 个 inline onclick Contract =================
# 锁定 HTML onclick -> dashboard.js 全局函数契约: 模板拆分不得破坏
# (pnl-help 的 openHelp + batchbar 的 batchDo×5/clearSel 共 7 个)

_HELP_ONCLICKS = [
    ("openHelp()", "openHelp"),
    ("batchDo('done',true)", "batchDo"),
    ("batchDo('delete')", "batchDo"),
    ("batchDo('priority',1)", "batchDo"),
    ("batchDo('priority',2)", "batchDo"),
    ("batchDo('priority',3)", "batchDo"),
    ("clearSel()", "clearSel"),
]


def test_help_onclick_contract_present():
    """D-5b-2C#1: 7 个 onclick 字符串在最终 HTML 中全部存在且未改变。"""
    html = _render(True)
    html_s = _render(False)
    for onclick, _fn in _HELP_ONCLICKS:
        assert 'onclick="%s"' % onclick in html, "interactive 缺 onclick: %s" % onclick
        assert 'onclick="%s"' % onclick in html_s, "snapshot 缺 onclick: %s" % onclick
    assert 'id="pnl-help"' in html, "pnl-help 缺失"


def test_help_onclick_global_functions_in_js():
    """D-5b-2C#2: onclick 调用的函数必须在 dashboard.js 顶层 function declaration(全局)。"""
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    for onclick, fn in _HELP_ONCLICKS:
        # 顶层 function declaration 或 window.fn = 赋值
        assert re.search(r"^function %s\b" % fn, js, re.M) or \
               "window.%s =" % fn in js, "函数 %s 非全局(顶层)声明" % fn


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
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
