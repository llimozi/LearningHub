# -*- coding: utf-8 -*-
"""icon_contract_test.py —— .ni 矢量图标匹配型契约 (v1.0 · 纯标准库)

背景（2026-08-31 审查, refactor_phase2/44）：
  图标机制 = <i class="ni">emoji</i> + CSS mask-image（font-size:0 隐藏 emoji）。
  隐式契约：模板 id/结构 ↔ CSS 选择器，漏配即渲染为空白块。
  旧防线 ui_refactor_test 的 `count("mask-image") >= 9` 是数量下限断言（伪保护）：
  Task06 的 8 个按钮控件漏配一路通过 371 例抵达提交。

本测试改为**匹配型**契约（A 存在 ⇒ B 必须存在），三层锁定：
  1. 正向逐元素：渲染产物中每个 .ni，必须匹配到至少一条含 mask-image
     且引用其祖先 id / href 的 CSS 规则（空白图标 = 立即 FAIL）。
  2. 反向悬空：CSS 中含 mask-image 的 .ni 规则，其引用的 #id / href
     必须存在于渲染产物（防选择器指向已删除/改名的控件）。
  3. Task06 控件点名：8 个按钮控件逐个断言「元素存在 + 规则存在」双事实，
     附测试函数名以满足 AGENTS.md §11 验收证据要求。

覆盖范围：dashboard 最终渲染 HTML（editor.html 现无 .ni，纳入将随 UI 演进补充）。
"""
import io
import os
import re
import sys
import unittest.mock as _mock
from html.parser import HTMLParser

import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_BASE = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_BASE, "templates", "dashboard.css")
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")

# ---------- render 隔离（同 html_contract_test 基架） ----------
def _render(interactive=True, theme_name="dark"):
    with _mock.patch.object(_services, "init_today_from_daily", return_value=(None, 0)), \
         _mock.patch.object(_services, "auto_catchup", return_value=[]), \
         _mock.patch.object(_planner, "normalize_priorities", return_value=0), \
         _mock.patch.object(_renderer.render_data.mastery, "weak_concepts", return_value=[]), \
         _mock.patch.object(_renderer.render_data.analyzer, "update_analysis", return_value=(None, [])), \
         _mock.patch.object(_renderer.render_data.forgetting, "sync_from_analysis", return_value=(None, 0)), \
         _mock.patch.object(_renderer.theme, "current_theme", return_value=theme_name):
        return _renderer.render(interactive)


# ---------- HTML 解析：收集 .ni 元素及其祖先定位键 ----------
class _NiCollector(HTMLParser):
    """收集 <i class="ni"> 元素；定位键 = 祖先 id 全集 + 祖先 <a href> + 父级 class。"""

    def __init__(self):
        super().__init__()
        self.stack = []          # [(tag, attrs_dict)]
        self.elements = []       # [{keys, emoji, owner}]

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        self.stack.append((tag, ad))
        if tag == "i" and "ni" in (ad.get("class") or "").split():
            keys = set()
            owner = "?"
            for t, a in reversed(self.stack[:-1]):
                if a.get("id"):
                    keys.add(a["id"])
                    if owner == "?":
                        owner = a["id"]
                if t == "a" and a.get("href"):
                    keys.add('href="%s"' % a["href"])
            cls = (ad.get("class") or "")
            self.elements.append({"keys": keys, "emoji": "", "owner": owner, "cls": cls})

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.elements and not self.elements[-1]["emoji"]:
            self.elements[-1]["emoji"] = data.strip()[:4]


def _collect_ni(html):
    p = _NiCollector()
    p.feed(html)
    return p.elements


# ---------- CSS 解析：抽出含 mask-image 的 .ni 规则 ----------
def _mask_rules(css):
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip(), m.group(2)
        if ".ni" in sel and "mask-image" in body:
            out.append((sel, body))
    return out


def _rule_matches(rule_sel, keys):
    """规则选择器须引用元素的某个定位键（id 或 href）。"""
    return any(k in rule_sel for k in keys)


# ---------- 共享夹具 ----------
def _load():
    html = _render(True)
    with io.open(_CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()
    return html, css, _collect_ni(html), _mask_rules(css)


# ---------- 1. 正向逐元素匹配（核心契约） ----------
def test_every_ni_element_has_mask_rule():
    html, css, elems, rules = _load()
    assert elems, "渲染产物中未发现任何 .ni 元素（图标机制失效）"
    assert rules, "CSS 中未发现任何含 mask-image 的 .ni 规则"
    misses = []
    for el in elems:
        if not any(_rule_matches(sel, el["keys"]) for sel, _b in rules):
            misses.append(el)
    assert not misses, (
        "%d 个 .ni 元素未匹配到任何 mask 规则(将渲染为空白块): %s"
        % (len(misses), [(m["owner"], m["emoji"], sorted(m["keys"])) for m in misses][:8]))


# ---------- 2. 反向悬空选择器 ----------
def test_no_dangling_mask_selectors():
    html, css, elems, rules = _load()
    ids = set(re.findall(r'(?<![a-zA-Z-])id="([a-z0-9_-]+)"', html))
    hrefs = set(re.findall(r'href="([^"]+)"', html))
    dangling = []
    for sel, _b in rules:
        for rid in re.findall(r"#([a-z0-9_-]+)", sel):
            if rid not in ids:
                dangling.append((sel, "id #%s 不存在" % rid))
        for m in re.findall(r'href="([^"]+)"', sel):
            if m not in hrefs:
                dangling.append((sel, "href %s 不存在" % m))
    assert not dangling, "CSS mask 规则引用了不存在的目标(悬空选择器): %s" % dangling[:8]


# ---------- 3. emoji 隐藏机制（mask 生效的前提） ----------
def test_ni_emoji_hiding_mechanism():
    _html, css, _elems, _rules = _load()
    m = re.search(r"\.btn \.ni\{[^}]*\}", css)
    assert m, "缺 .btn .ni 基类规则"
    assert "font-size:0" in m.group(0), ".btn .ni 未隐藏 emoji(font-size:0)"
    m2 = re.search(r"\.card h2 \.ni\{[^}]*\}", css)
    assert m2 and "font-size:0" in m2.group(0), ".card h2 .ni 未隐藏 emoji(font-size:0)"


# ---------- 4. Task06 按钮控件点名（双事实：元素在 + 规则在） ----------
# 每项: (CSS 规则须引用的 id, 元素须包含的 emoji 文本)
TASK06_CONTROLS = [
    ("btn-capture", "➕"),   # 快捕
    ("btn-note", "📝"),      # 写笔记（曾漏配 → 空白图标, 见 refactor_phase2/44）
    ("btnweek", "🔄"),       # 生成周报
    ("btn-batchmode", "☑"),  # 批量模式
    ("btn-backfill", "🕐"),  # 补记完成时刻
    ("redbadge", "🛡"),      # 减负徽章
]


def test_task06_controls_element_and_rule_pairs():
    html, css, elems, rules = _load()
    by_owner = {}
    for el in elems:
        by_owner.setdefault(el["owner"], []).append(el)
    for cid, emoji in TASK06_CONTROLS:
        # 事实 A: 元素存在且含预期 emoji
        cands = by_owner.get(cid, [])
        assert cands, "控件 #%s 缺少 .ni 元素(模板漏配)" % cid
        assert any(emoji in e["emoji"] for e in cands), \
            "控件 #%s 的 .ni emoji 不符: %r" % (cid, [e["emoji"] for e in cands])
        # 事实 B: CSS 存在引用该 id 的 mask 规则
        assert any(cid in sel for sel, _b in rules), \
            "控件 #%s 缺少含 mask-image 的 CSS 规则(将渲染空白块)" % cid


def test_task06_container_scoped_controls():
    """#pnl-review .btn-mini .ni（复习打卡）与 #pnl-help .btn .ni（打开帮助）:
    按钮自身无 id, 靠容器 id 定位 —— 正向匹配 + 点名规则双保险。"""
    html, css, elems, rules = _load()
    for cid, selfrag in (("pnl-review", "#pnl-review .btn-mini .ni"),
                         ("pnl-help", "#pnl-help .btn .ni")):
        inside = [e for e in elems if cid in e["keys"]]
        assert inside, "容器 #%s 内未发现 .ni 元素" % cid
        assert any(selfrag in sel for sel, _b in rules), "缺规则 %s" % selfrag


def test_batchmode_dual_state_keeps_icon():
    """batchmode 切换用 innerHTML 重建按钮内容（dashboard.js）,
    两态都必须保留 <i class="ni"> 前缀, 否则切换后图标丢失。"""
    with io.open(_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()
    m = re.search(r"bmBtn\.innerHTML\s*=\s*([^;]+);", js)
    assert m, "batchmode 双态切换语句缺失"
    assert '<i class="ni">' in m.group(1), "batchmode 切换未保留 .ni 图标前缀"


def test_btn_mini_icon_color_rule():
    """中性 .btn-mini 的图标颜色契约（2026-08-31 缺陷回归防线）:
    复习打卡按钮(#pnl-review .btn-mini)曾因只配 mask 未配颜色, 继承 .btn .ni 的
    on-accent(暗色主题近黑), 三主题对比度 1.04:1 不可见。
    契约: .btn-mini .ni 规则必须存在且声明 background-color:var(--body)
    (与 .btn-mini 文字色一致; 与 .btn-ghost .ni 同源)。"""
    _html, css, _elems, _rules = _load()
    m = re.search(r"\.btn-mini \.ni\{([^}]*)\}", css)
    assert m, "缺 .btn-mini .ni 颜色规则(图标将继承 on-accent 致暗色不可见)"
    body = m.group(1)
    assert "background-color:var(--body)" in body, \
        ".btn-mini .ni 颜色非 var(--body): %r" % body


# ---------- 5. 汇总一致性 ----------
def test_mask_rule_count_stable():
    """规则总数备案（非覆盖依据, 仅防意外批量丢失）:
    8 导航(href) + 15 面板标题(h2, 含 setcard-wrap/help) + 8 按钮控件 = 31
    条含 mask-image 的 .ni 规则（分类实测于 2026-08-31, 见 refactor_phase2/44）。"""
    _html, css, _elems, rules = _load()
    assert len(rules) == 31, "mask 规则数 %d != 备案 31, 若为有意变更请同步更新本测试与注释" % len(rules)


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
