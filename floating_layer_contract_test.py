# -*- coding: utf-8 -*-
"""floating_layer_contract_test.py —— D-5b-3-0 Floating Layer & Modal Contract Gate (v1.1)

为 D-5b-3B/3C 浮层拆分建立自动化安全门(纯标准库, 不依赖浏览器):
  1. 浮层 DOM 存在 + id 唯一 + 最终 HTML 可寻址
  2. JS 关键子结构 id(JS getElementById 依赖)
  3. 默认隐藏状态(HTML 层面 display:none 特征)
  4. Inline onclick -> dashboard.js 全局函数 Contract 扩展
  5. modal: DOM 存在 + onclick 保留 + 隐藏特征

⚠️ modal 的 computed style(--card/--border2 三主题)由浏览器探针验证
(视觉回归对 display:none 元素盲区, 本文件单元层 + 探针运行时层双层覆盖)。
"""
import os
import re
import sys
import unittest.mock as _mock

import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_BASE = os.path.dirname(os.path.abspath(__file__))
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")

# 目标浮层(3B) + modal(3C 敏感)
FLOATING_LAYERS = ["ksearch", "cmdk", "dtpick", "guide", "modal"]
# 浮层关键子结构(JS getElementById 实际依赖)
JS_SUB_IDS = {
    "ksearch": ["ksinput", "ksres"],
    "cmdk": ["cmdk-input", "cmdk-res"],
    "dtpick": ["dt-desc", "dt-input", "dt-actual", "dt-cancel", "dt-apply"],
    "guide": ["gt", "gd", "gdir", "gdots", "gprev", "gnext"],
    "modal": ["mtitle", "mbody"],
}
# 隐藏特征: 内联 display:none 或容器 class 关联(guidewrap/ctx/ksearch 等)
HIDDEN_CLASSES = ["guidewrap", "ctx", "ksearch", "cmdkwrap", "modalwrap"]


def _render(interactive=True, theme_name="dark"):
    with _mock.patch.object(_services, "init_today_from_daily", return_value=(None, 0)), \
         _mock.patch.object(_services, "auto_catchup", return_value=[]), \
         _mock.patch.object(_planner, "normalize_priorities", return_value=0), \
         _mock.patch.object(_renderer.render_data.mastery, "weak_concepts", return_value=[]), \
         _mock.patch.object(_renderer.render_data.analyzer, "update_analysis", return_value=(None, [])), \
         _mock.patch.object(_renderer.render_data.forgetting, "sync_from_analysis", return_value=(None, 0)), \
         _mock.patch.object(_renderer.theme, "current_theme", return_value=theme_name):
        return _renderer.render(interactive)


def _html_ids(html):
    return set(re.findall(r'(?<![a-zA-Z-])id="([a-z0-9_-]+)"', html))


def test_floating_layers_exist_unique():
    """1: 5 个浮层(DOM 容器)在最终 HTML 存在且 id 唯一(双模式)。"""
    for mode in (True, False):
        html = _render(mode)
        ids = _html_ids(html)
        for fl in FLOATING_LAYERS:
            assert fl in ids, "浮层 %s 缺失(mode=%s)" % (fl, mode)
        for i in re.finditer(r'(?<![a-zA-Z-])id="([a-z0-9_-]+)"', html):
            assert len(re.findall(r'(?<![a-zA-Z-])id="%s"' % i.group(1), html)) == 1, "id 重复: %s" % i.group(1)


def test_floating_layer_js_sub_ids():
    """2: JS getElementById 依赖的浮层子结构 id 全部可寻址。"""
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    js_ids = set(re.findall(r"getElementById\(['\"]([a-z0-9_-]+)['\"]\)", js))
    for mode in (True, False):
        html = _render(mode)
        ids = _html_ids(html)
        for fl, subs in JS_SUB_IDS.items():
            for sid in subs:
                assert sid in ids, "浮层 %s 子 id %s 缺失(mode=%s)" % (fl, sid, mode)
                assert sid in js_ids, "子 id %s 不在 JS 依赖中(契约不匹配)" % sid


def test_floating_layer_hidden_state():
    """3: 浮层默认隐藏(容器 class 关联 display:none 或内联样式)。"""
    html = _render(True)
    for fl in FLOATING_LAYERS:
        m = re.search(r'<div[^>]*id="%s"[^>]*>' % fl, html)
        assert m, "浮层 %s 标签未找到" % fl
        tag = m.group(0)
        # 内联隐藏 或 class 在隐藏类中
        inline_hidden = 'display:none' in tag or "display: none" in tag
        class_hidden = any(c in tag for c in HIDDEN_CLASSES)
        assert inline_hidden or class_hidden, "浮层 %s 无隐藏特征: %s" % (fl, tag[:80])


def test_floating_onclick_global_functions():
    """4: 浮层 inline onclick 调用的函数必须在 dashboard.js 顶层声明(全局)。"""
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    html = _render(True)
    # 目标 onclick 函数(实际浮层事件)
    target_fns = ["setpri", "snoPick", "guideStep", "guideNext", "guideFinish", "copyReport"]
    for fn in target_fns:
        assert re.search(r"^function %s\b" % fn, js, re.M) or \
               "window.%s =" % fn in js, "函数 %s 非全局声明" % fn
    # modal onclick 保留
    assert "copyReport()" in html, "modal copyReport onclick 缺失"
    assert "guideNext()" in html, "guide onclick 缺失"
    assert "setpri(1)" in html, "ctxmenu onclick 缺失"


def test_modal_contract_preserved():
    """5: modal 结构保持(DD-02 敏感): id/onclick/隐藏特征。"""
    html = _render(True)
    assert 'id="modal"' in html and 'id="mtitle"' in html and 'id="mbody"' in html, "modal 结构缺失"
    assert "modalwrap" in html, "modal 容器 class 缺失"
    assert 'onclick="copyReport()"' in html, "modal copyReport onclick 缺失"
    m = re.search(r'<div[^>]*id="modal"[^>]*>', html)
    assert m and "modalwrap" in m.group(0), "modal 容器隐藏特征缺失"


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
