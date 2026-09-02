# -*- coding: utf-8 -*-
"""theme_test.py —— 主题系统单元测试 (v1.3 · 纯标准库)
跑法A: pytest theme_test.py      跑法B: python theme_test.py (零依赖runner)
覆盖: 三套暗色主题齐备且互异 / 变量集完整且值合法 / 未知主题回退默认 /
      CSS 输出形态(:root 块+变量序稳定) / set_theme 归一化持久化与非法回退 /
      dashboard 与 editor 两套覆盖规则都引用变量。
"""
import json
import os
import re
import shutil
import tempfile

from theme import (THEMES, DEFAULT_THEME, REQUIRED_VARS,
                   get_theme, theme_root_css, override_css, set_theme)


def test_three_dark_themes_with_chinese_labels():
    assert set(THEMES.keys()) == {"dark", "midnight-blue", "ink-green"}
    labels = [THEMES[k]["label"] for k in ("dark", "midnight-blue", "ink-green")]
    assert all(labels), labels
    assert "深空灰" in labels[0] and "墨绿" in labels[2]


def test_every_theme_covers_required_vars_with_hex():
    hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
    for name, spec in THEMES.items():
        missing = [v for v in REQUIRED_VARS if v not in spec["vars"]]
        assert not missing, (name, missing)
        for var, val in spec["vars"].items():
            assert hex_re.match(val), (name, var, val)


def test_themes_visually_distinct_by_bg():
    bgs = {name: spec["vars"]["--bg"] for name, spec in THEMES.items()}
    assert len(set(bgs.values())) == len(bgs), bgs


def test_get_theme_unknown_falls_back_to_default():
    spec = get_theme("不存在的主题")
    assert spec == THEMES[DEFAULT_THEME]


def test_theme_root_css_shape_and_stable_order():
    css = theme_root_css("midnight-blue")
    assert css.startswith(":root{") and css.rstrip().endswith("}")
    found = re.findall(r"--[a-z0-9-]+:", css)
    assert found == [v + ":" for v in REQUIRED_VARS], found      # 顺序稳定可测


def test_set_theme_normalizes_and_persists():
    d = tempfile.mkdtemp()
    try:
        out = set_theme(d, "  Ink-Green ")
        assert out == "ink-green"
        saved = json.load(open(os.path.join(d, "settings.json"), encoding="utf-8-sig"))
        assert saved["theme"] == "ink-green"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_set_theme_invalid_heals_stored_garbage():
    d = tempfile.mkdtemp()
    try:
        _write(os.path.join(d, "settings.json"), {"theme": "赛博朋克粉"})
        out = set_theme(d, "也不合法")
        assert out == DEFAULT_THEME
        saved = json.load(open(os.path.join(d, "settings.json"), encoding="utf-8-sig"))
        assert saved["theme"] == DEFAULT_THEME                   # 存量垃圾被自愈归一
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_set_theme_invalid_on_fresh_dir_zero_write():
    d = tempfile.mkdtemp()
    try:
        out = set_theme(d, "随便什么")
        assert out == DEFAULT_THEME                              # 返回值兜底
        # 全新目录+请求即默认: 允许零写盘(与空闲零IO原则一致), 不强制落档
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _write(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump(obj, f, ensure_ascii=False)


def test_override_css_targets_reference_vars():
    dash = override_css("ink-green", target="dashboard")
    ed = override_css("ink-green", target="editor")
    assert ":root{" in dash and ":root{" in ed
    assert "--bg:" in dash and "--bg:" in ed
    assert "var(--" in dash                                  # dashboard 覆盖层消费变量(R06 等保留)
    # Batch 2C: dashboard 等价覆盖层已逐批删除(2C-1 删 23 条, 2C-2 删 L95 行内),
    # 仅剩 .modal(DD-02 方案 A 保留, 非等价项); 断言转向"注入核心正确"
    assert dash.count("!important") >= 1, "dashboard 覆盖层应至少保留 .modal(DD-02 保留)"
    assert ed.count("!important") == 0, "editor 覆盖层应已清零(Batch 2B-1)"


def test_override_rules_differ_between_targets():
    dash = override_css("dark", target="dashboard")
    ed = override_css("dark", target="editor")
    assert ":root{" in dash and ":root{" in ed
    # Batch 2C: dashboard 等价覆盖层逐批删除, 注入侧规则减少中(R06 保留至 2C-2);
    # 分流验证改由 dash != ed 保证, 不依赖具体 selector 名
    assert dash != ed                                      # 两端注入文本不同


# ================= P1 回归: renderer 必须注入 theme CSS 到 dashboard 页面 =================
# 背景: FOLLOWUP #14 — renderer.py 模板 L312 曾写成空 <style id="themecss"></style>,
# 丢失 __THEMECSS__ 占位符, 导致 L1910 的 .replace() 静默失效, dashboard 三主题渲染完全相同。
# 以下测试直接调用 renderer.render() 检查注入产物, 把"占位符丢失"变成测试失败。

import unittest.mock as _mock
import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_THEME_NAMES = ("dark", "midnight-blue", "ink-green")


def _render_isolated(theme_name):
    """以指定主题渲染 dashboard, 隔离所有写盘副作用(init/rollover/priority/mastery/analysis)。

    P1 核验补充: render() 会真实调用 mastery.weak_concepts → update_mastery_scores,
    mastery_score 随日期衰减必然 changed → 实测写盘 daily/knowledge.json(测试污染)。
    analyzer.update_analysis / forgetting.sync_from_analysis 同为写盘路径(防御性隔离),
    保证新增 4 例零数据副作用。
    """
    with _mock.patch.object(_services, "init_today_from_daily", return_value=(None, 0)), \
         _mock.patch.object(_services, "auto_catchup", return_value=[]), \
         _mock.patch.object(_planner, "normalize_priorities", return_value=0), \
         _mock.patch.object(_renderer.render_data.mastery, "weak_concepts", return_value=[]), \
         _mock.patch.object(_renderer.render_data.analyzer, "update_analysis", return_value=(None, [])), \
         _mock.patch.object(_renderer.render_data.forgetting, "sync_from_analysis", return_value=(None, 0)), \
         _mock.patch.object(_renderer.theme, "current_theme", return_value=theme_name):
        return _renderer.render(False)


def _extract_themecss(html):
    """从渲染 HTML 提取 <style id="themecss"> 内容; 无该标签或为空则抛 AssertionError。"""
    m = re.search(r'<style id="themecss">(.*?)</style>', html, re.S)
    assert m, "渲染 HTML 中找不到 <style id=\"themecss\"> 标签"
    return m.group(1)


def test_render_injects_theme_css_nonempty():
    """P1#1 注入: render() 输出中 themecss 非空, 且为 :root 变量块 + 覆盖规则。"""
    html = _render_isolated("dark")
    css = _extract_themecss(html)
    assert css.strip(), "themecss 为空 —— __THEMECSS__ 占位符替换失效(FOLLOWUP #14 复发)"
    assert ":root{" in css and "--bg:" in css, "themecss 缺 :root 变量块"
    assert "var(--" in css, "themecss 缺变量引用(覆盖规则必须消费变量)"


def test_render_html_no_literal_placeholder():
    """P1#2 无残留: 渲染后 HTML 中不得出现字面 __THEMECSS__/__CSS__ 占位符。"""
    html = _render_isolated("dark")
    assert "__THEMECSS__" not in html, "HTML 残留字面 __THEMECSS__ 占位符"
    assert "__CSS__" not in html, "HTML 残留字面 __CSS__ 占位符"


def test_render_three_themes_distinct():
    """P1#3 三主题互异: dark/midnight-blue/ink-green 渲染出的 themecss 与页面 body 变量均不同。"""
    css_map = {}
    for name in _THEME_NAMES:
        html = _render_isolated(name)
        css_map[name] = _extract_themecss(html)
        assert "--bg:#" in css_map[name], (name, "缺 --bg 变量")
    assert css_map["dark"] != css_map["midnight-blue"], "dark 与 midnight-blue 渲染相同"
    assert css_map["midnight-blue"] != css_map["ink-green"], "midnight-blue 与 ink-green 渲染相同"
    assert css_map["dark"] != css_map["ink-green"], "dark 与 ink-green 渲染相同"
    # 变量根必须体现主题差异(不再是同一份 dark 硬编码)
    bg_values = {name: re.search(r"--bg:#([0-9a-fA-F]{6})", css_map[name]).group(1) for name in _THEME_NAMES}
    assert len(set(bg_values.values())) == 3, bg_values


def test_render_theme_reflects_settings_change():
    """P1#4 刷新保持的单元级代理: current_theme 返回值变化 => 渲染产物变化(服务端实时读 settings)。"""
    html_dark = _render_isolated("dark")
    html_green = _render_isolated("ink-green")
    css_dark = _extract_themecss(html_dark)
    css_green = _extract_themecss(html_green)
    assert "--bg:#08090A" in css_dark, "dark 渲染应含 #08090A"
    assert "--bg:#070A08" in css_green, "ink-green 渲染应含 #070A08"
    assert "--card:#0F1011" in css_dark and "--card:#0D110E" in css_green


# ================= Batch 2B-0: Editor 注入契约测试 =================
# 背景: server.py L318 用 ed_html.replace("<style>", "<style>"+ed_css, 1) 注入主题 CSS,
# 锚点是 editor.html 中"恰好 1 个字面 <style> 标签"的隐式契约; 注入失败双重静默
# (replace 无匹配不报错 + except Exception: pass), 且此前无任何测试能发现注入失效。
# 以下测试把该契约显式化: anchor 消失/增变/注入产物缺失 → 测试 FAIL。

_EDITOR_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor.html")


def _load_editor_html():
    assert os.path.exists(_EDITOR_HTML), "editor.html 缺失"
    with open(_EDITOR_HTML, encoding="utf-8") as _f:
        return _f.read()


def _simulate_editor_injection(html, theme_name):
    """与 server.py L317-318 完全相同的注入逻辑(读 override_css + 首个 <style> 后插入)。"""
    ed_css = override_css(theme_name, target="editor")
    return html.replace("<style>", "<style>" + ed_css, 1)


def test_editor_html_has_single_style_anchor():
    """Batch2B-0#1 anchor 契约: editor.html 必须恰好 1 个 <style> 开标签且不在 <script> 内。"""
    html = _load_editor_html()
    assert html.count("<style>") == 1, "editor.html 的 <style> 开标签数 != 1 (注入锚点失效风险)"
    assert html.count("</style>") == 1, "editor.html 的 </style> 数 != 1"
    # <script> 区域内不得出现 <style> 字面量(否则注入点会误入 JS)
    script_bodies = re.findall(r"<script>(.*?)</script>", html, re.S)
    for sb in script_bodies:
        assert "<style" not in sb, "script 区域内出现 <style> 字面量, 注入可能误入 JS"


def test_editor_injection_places_theme_css():
    """Batch2B-0#2 (收尾更新): editor 覆盖层已全部迁入原生 var 化, 注入侧仅 :root,
    无 editor 覆盖规则注释; 原生样式(v0.5 编辑器)仍保留。"""
    html = _load_editor_html()
    out = _simulate_editor_injection(html, "dark")
    head = out[: out.index("</head>")]
    assert ":root{" in head, "注入后 head 无 :root 变量块 (注入失效)"
    assert "v0.5 编辑器" in head, "原生样式丢失 (注入不应破坏原生 CSS)"
    assert "v1.3 主题覆盖层(editor)" not in head, "editor 覆盖层已迁入原生, 注释不应残留"
    assert head.count("<style>") == 1, "注入后 <style> 开标签数应仍为 1 (内容合并, 非新开块)"
    assert out.count("</style>") == 1, "注入后 </style> 数应仍为 1"


def test_editor_three_themes_inject_distinct():
    """Batch2B-0#3 三主题互异: editor 注入产物随主题不同(--bg 值来自 THEMES 表)。"""
    html = _load_editor_html()
    css_map = {}
    for name in ("dark", "midnight-blue", "ink-green"):
        out = _simulate_editor_injection(html, name)
        m = re.search(r":root\{--bg:#([0-9a-fA-F]{6})", out)
        assert m, (name, "注入产物缺 --bg")
        css_map[name] = m.group(1)
    assert css_map["dark"] != css_map["midnight-blue"], "dark 与 midnight-blue 注入相同"
    assert css_map["midnight-blue"] != css_map["ink-green"], "midnight-blue 与 ink-green 注入相同"
    # token 一致性: 注入的 --bg 必须与 THEMES 表定义一致
    for name, hexv in css_map.items():
        assert hexv == THEMES[name]["vars"]["--bg"].lstrip("#"), (name, "注入 --bg 与 THEMES 表不一致")


def test_editor_injection_missing_anchor_detected():
    """Batch2B-0#4 哨兵: 若 editor.html 失去 <style> 锚点, 注入产物不含 :root ——
    证明本测试机制能捕获注入失效(dashboard P1 同型事故在 editor 侧可被发现)。"""
    html = _load_editor_html()
    out = _simulate_editor_injection(html, "dark")
    # 正向: 当前有 anchor 时必须注入成功
    assert ":root{" in out
    # 反向: 人为移除 anchor 后, 模拟 server 注入必须失败(验证 replace 静默特性可被断言捕获)
    stripped = html.replace("<style>", "", 1)
    out2 = _simulate_editor_injection(stripped, "dark")
    assert ":root{" not in out2, "无 anchor 时注入竟成功 —— 契约与预期不符"


def test_editor_theme_css_consumes_vars_only():
    """Batch2B-0#5 (收尾更新): editor 覆盖层已全部迁入 editor.html 原生 var 化,
    注入侧仅 :root, 无 !important; dashboard 覆盖规则继续消费变量、零硬编码。"""
    ed = override_css("dark", target="editor")
    assert ed == theme_root_css("dark"), "editor 注入应仅 :root(覆盖层已迁入原生)"
    assert "!important" not in ed, "editor 注入应不含 !important(覆盖层清零)"
    dash = override_css("dark", target="dashboard")
    rules = dash.split("\n", 1)[1]
    hardcoded = re.findall(r"#[0-9a-fA-F]{3,8}|rgb\(|rgba\(", rules)
    assert not hardcoded, "dashboard 覆盖规则含硬编码色值: %s" % hardcoded[:5]


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
