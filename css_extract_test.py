# -*- coding: utf-8 -*-
"""css_extract_test.py —— D-8-1 CSS 外链回归测试 (v1.1 · 纯标准库)

验证: dashboard.css 外链后(D-8-1, 镜像 D-5a JS 外链模式)
  1. dashboard.css 文件存在、非空、不含未替换 placeholder
  2. render(interactive=True) 输出引用 /dashboard.css(link), 不含内联 varroot
  3. render(interactive=False) 快照保持自包含(内联 varroot style)
  4. 顺序契约: CSS 源(link/varroot)必须位于 themecss 主题覆盖层之前
  5. renderer.py 无 __PNL_HEAD__ 占位残留 + 外链 link 模板存在
  6. dashboard.css 语法粗检(花括号配平)

防止未来 CSS 又被塞回 renderer.py / 双模式退化 / 顺序颠倒。
"""
import os
import re
import sys
import unittest.mock as _mock

import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_BASE = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_BASE, "templates", "dashboard.css")
_RENDERER_PATH = os.path.join(_BASE, "_app", "renderer.py")
_TPL_PATH = os.path.join(_BASE, "_app", "render_templates.py")


def _render(interactive):
    """隔离写盘副作用渲染。"""
    with _mock.patch.object(_services, "init_today_from_daily", return_value=(None, 0)), \
         _mock.patch.object(_services, "auto_catchup", return_value=[]), \
         _mock.patch.object(_planner, "normalize_priorities", return_value=0), \
         _mock.patch.object(_renderer.render_data.mastery, "weak_concepts", return_value=[]), \
         _mock.patch.object(_renderer.render_data.analyzer, "update_analysis", return_value=(None, [])), \
         _mock.patch.object(_renderer.render_data.forgetting, "sync_from_analysis", return_value=(None, 0)):
        return _renderer.render(interactive)


def test_dashboard_css_exists_and_clean():
    """1/6: dashboard.css 存在、非空、不含未替换 placeholder。"""
    assert os.path.exists(_CSS_PATH), "templates/dashboard.css 缺失"
    with open(_CSS_PATH, encoding="utf-8") as f:
        css = f.read()
    assert len(css.strip()) > 1000, "dashboard.css 过短(疑似空壳)"
    assert not re.search(r"__[A-Z_]{2,}__", css), "dashboard.css 含未替换 placeholder"


def test_interactive_html_references_external_css():
    """2/6: interactive 输出引用 /dashboard.css(link), 不含内联 varroot。"""
    html = _render(True)
    assert 'link rel="stylesheet" href="/dashboard.css"' in html, "interactive 缺外链 CSS link"
    assert '<style id="varroot">' not in html, "interactive 仍内联 varroot(D-8-1 未生效)"
    assert '<style id="themecss">' in html, "interactive 缺 themecss 主题层"


def test_snapshot_html_stays_self_contained():
    """3/6: 快照模式保持自包含: varroot 内联, 不引用外链 CSS。"""
    html = _render(False)
    assert '<style id="varroot">' in html, "快照 HTML 缺内联 varroot(自包含能力丢失)"
    assert 'href="/dashboard.css"' not in html, "快照不应引用外链 CSS"
    assert '<style id="themecss">' in html, "快照缺 themecss"


def test_css_source_before_themecss_order():
    """4/6: 顺序契约——CSS 源(link/varroot)必须位于 themecss 之前(CSS 级联源顺序)。"""
    for mode in (True, False):
        html = _render(mode)
        i_css = html.find('href="/dashboard.css"' if mode else '<style id="varroot">')
        i_theme = html.find('<style id="themecss">')
        assert i_css != -1 and i_theme != -1, "CSS 源或 themecss 缺失(mode=%s)" % mode
        assert i_css < i_theme, "顺序错误: CSS 源(%d)必须在 themecss(%d)之前" % (i_css, i_theme)


def test_renderer_no_css_leftovers():
    """5/6: renderer/render_templates 的 CSS 相关占位符配对 + 双模式模板存在。"""
    with open(_RENDERER_PATH, encoding="utf-8") as f:
        rsrc = f.read()
    with open(_TPL_PATH, encoding="utf-8") as f:
        tsrc = f.read()
    cnt = rsrc.count("__PNL_HEAD__")
    assert cnt >= 2, "占位符 __PNL_HEAD__ 出现 %d 次(应>=2: 模板+replace配对)" % cnt
    # 双模式分支必须存在: interactive link + snapshot varroot style
    assert 'href="/dashboard.css"' in tsrc, "render_templates 缺外链 link 模板"
    assert '<style id="varroot">' in tsrc, "render_templates 缺快照 varroot 模板"
    assert "interactive" in tsrc, "render_templates 缺 interactive 分支"


def test_dashboard_css_syntax_balanced():
    """6/6: dashboard.css 花括号配平(粗粒度 sanity)。"""
    with open(_CSS_PATH, encoding="utf-8") as f:
        css = f.read()
    assert css.count("{") == css.count("}"), "dashboard.css 花括号不配平"


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
