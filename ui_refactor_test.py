# -*- coding: utf-8 -*-
"""ui_refactor_test.py —— UI 重构不变量测试 (v2.5 · 纯标准库)

跑法A: pytest ui_refactor_test.py      跑法B: python ui_refactor_test.py (零依赖runner)
覆盖目标: 确认 v2.4 毛玻璃层 + v2.5 高级克制层已注入且不破坏既有约束——
  1) 玻璃层存在(@supports + backdrop-filter + 半透明玻璃面)
  2) 降级安全(玻璃规则在 @supports 内, 不支持浏览器回落地色)
  3) 排版规整(有效字重归一四档 + 桌面正文 ≥16px)
  4) 输入框聚焦环已补齐
  5) JS 依赖的结构类未被改名/删除
  6) L4「DO NOT MODIFY」稳定边界注释未被移除
  7) v2.5 高级克制层: emoji→矢量图标 / hero 焦点 / 内容宽收拢 / 状态色克制
"""
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
CSS_PATH = os.path.join(BASE, "templates", "dashboard.css")


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


def test_glass_layer_installed():
    css = _css()
    # 毛玻璃层的主特征齐全且位于文件末尾(L5)
    assert "@supports (backdrop-filter: blur(1px))" in css, "缺 @supports 玻璃层"
    assert "玻璃拟态层" in css, "缺玻璃层注释"
    assert "backdrop-filter: blur(14px) saturate(1.35)" in css, "缺主玻璃 blur"


def test_glass_surface_is_translucent():
    css = _css()
    # 卡片等主表面用 color-mix 从主题变量派生半透明玻璃面
    assert "color-mix(in srgb, var(--card) 68%, transparent)" in css, "卡片玻璃面非半透明"
    # 浮层用更亮一档(card2)
    assert "color-mix(in srgb, var(--card2) 72%, transparent)" in css, "浮层玻璃面缺失"


def test_glass_wrapped_for_graceful_fallback():
    css = _css()
    # backdrop-filter 只出现在 @supports 内(不支持浏览器走 L4 实体色, 不白屏)
    supports_start = css.find("@supports (backdrop-filter: blur(1px))")
    assert supports_start != -1, "找不到 @supports 包裹"
    # 主玻璃规则在 @supports 起始之后
    assert css.find("backdrop-filter: blur(14px)") > supports_start, "主 blur 未在 @supports 内"
    # 且 @supports 块有闭合(同一文件内 @supports 后仍有内容, 非悬挂)
    assert css.rstrip().endswith("}"), "@supports 块未正确闭合(文件尾部异常)"


def test_typography_normalized():
    css = _css()
    # 有效字重归一到四档(400/500/600/700), 任何位置有覆盖即满足
    assert "font-weight:400" in css, "缺正文 400 字重"
    assert "font-weight:500" in css, "缺 500 字重"
    assert "font-weight:600" in css, "缺 600 字重"
    assert "font-weight:700" in css, "缺标题 700 字重"
    # 桌面 B2B 正文基准: body 字号已提到 ≥16px
    assert "font-size:16px" in css, "body 未升到桌面基准 16px"


def test_radius_language_unified():
    css = _css()
    # 按钮/子卡/提示卡统一到语义圆角
    assert ".btn{border-radius:12px}" in css, "按钮圆角未统一"
    assert ".task,\n.rec{border-radius:12px}" in css, "任务/复习卡圆角未统一"


def test_input_focus_ring_added():
    css = _css()
    # 输入框聚焦环 + hover 边框已补齐(此前缺失)
    assert "input[type=text]:focus" in css, "缺输入框 focus 态"
    assert "box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent)" in css, "缺统一聚焦环"


def test_js_structural_selectors_preserved():
    css = _css()
    # 这些类被 build_dashboard.py 的 JS 依赖, 重构不得改名/删除
    for sel in (".task", ".ckitem", ".kb-focus", ".tdetail", ".rec", ".ksub", ".karrow"):
        assert sel in css, f"JS 依赖的结构类 {sel} 丢失"


def test_l4_stability_boundary_intact():
    css = _css()
    # L4 v2.2 的稳定边界注释必须仍在(未破坏基线)
    assert "DO NOT MODIFY" in css, "L4 稳定边界注释被移除"


def test_theme_contract_untouched():
    # 毛玻璃用 color-mix 派生半透明, 不应新增/改名主题变量→ 主题测试契约不变
    # 这里只做轻量复查: theme.py 的必需变量名集合未因本重构改变
    import theme
    assert set(theme.REQUIRED_VARS) == {
        "--bg", "--card", "--card2", "--hover", "--input",
        "--border", "--border2", "--body", "--text", "--dim",
        "--accent", "--accent-hov", "--good", "--bad", "--warn",
        "--tag-bg", "--pink"}, "主题变量集被改动(违反测试契约)"


# ------- v2.5 高级克制层(Premium/Sleek)验收 -------

def test_v25_premium_layer_installed():
    css = _css()
    assert "v2.5 高级克制层" in css, "缺 v2.5 高级克制层注释"


def test_emoji_icons_replaced_by_vector_masks():
    css = _css()
    # 导航/侧栏 .ni 图标改用 mask-image 矢量线条, 隐藏 emoji 文本(font-size:0)
    assert ".nav a .ni{" in css, "缺 .ni 矢量图标基类"
    assert "width:17px;height:17px" in css, "缺 .ni 尺寸"
    assert "font-size:0" in css, "emoji 文本未隐藏(应 font-size:0)"
    assert css.count("mask-image") >= 9, "矢量图标 mask 数量不足"
    # 核心导航项都有专属图标(href 分配)
    for href in ('#pnl-overview', '#pnl-tasks', '#pnl-heatmap',
                 '#pnl-review', '#pnl-graph', '#pnl-rec', '#pnl-progress',
                 '#setcard-wrap'):
        assert css.count('.nav a[href="%s"] .ni' % href) >= 1, "缺 %s 导航图标" % href


def test_focus_hero_card_present():
    css = _css()
    # 首屏总览 hero 区被单独强化(视觉焦点), 打破全网格同权重
    assert "#pnl-overview .card{" in css, "缺总览 hero 焦点强化"
    assert "#pnl-overview .big{" in css, "缺 hero 大数字强化"


def test_content_width_tightened():
    css = _css()
    # 内容宽从 1480 收拢到 ≤1360, 留白更松弛
    assert "--content-max-width:1360px" in css, "内容宽未收拢到 1360"


def test_state_colors_restrained():
    css = _css()
    # 正常/中性态回灰, 彩色只留给「值得注意」(styleseed 状态色=severity)
    assert ".task .status,.rec .meta span{color:var(--dim)}" in css, "中性态未回灰"
    assert "--accent-tint" in css, "缺主色微调(更清透蓝紫)"


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
