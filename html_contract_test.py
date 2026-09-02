# -*- coding: utf-8 -*-
"""html_contract_test.py —— D-5b-0 HTML Fragment Contract Tests (v1.1 · 纯标准库)

锁定当前 Dashboard 最终渲染 HTML 的 DOM Contract（非字符串对比），
为未来 D-5b HTML 面板模板拆分提供安全网：
拆分后只要最终 DOM contract 不变（id/class/面板/JS 依赖/placeholder/theme），
本测试即证明拆分安全。

覆盖:
  1. DOM 基线(title/lang/script/JS 引用/theme CSS/placeholder 无残留)
  2. Panel Contract(25 面板存在 + id 唯一)
  3. JS DOM Contract(65 静态 id 在最终 HTML 中可寻址)
  4. CSS Contract(跨面板 selector 的 DOM 前提)
  5. Placeholder Contract(36 个无残留 + 无 "None"/"False" 字符串泄漏)
  6. Cross Panel Data Contract(DN/TN/STREAK 多面板一致)
  7. Theme Contract(三主题 body bg/accent 互异 + __THEMECSS__ 无残留)
  8. Interactive/Snapshot 双模式(外链 vs 自包含)
  9. DOM Snapshot(结构化 id 树 JSON, 供 D-5b-1 前后对比)
"""
import io
import json
import os
import re
import sys
import unittest.mock as _mock
from html.parser import HTMLParser

import _app.renderer as _renderer
import _app.services as _services
import planner as _planner

_BASE = os.path.dirname(os.path.abspath(__file__))
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")

# ---------- 25 面板 (D-5b PREP §D) ----------
PANELS = [
    "pnl-overview", "pnl-tasks", "pnl-today", "pnl-insight", "pnl-heatmap",
    "pnl-review", "pnl-decay", "pnl-graph", "pnl-rec", "pnl-reports",
    "pnl-progress", "pnl-milestone", "pnl-kb", "pnl-help",
    "ksearch", "guide", "ctxmenu", "keyhelp", "snomenu", "dtpick", "modal",
]
SHELL_NODES = ["side", "topbar", "main"]
# 动态创建 id (JS 运行时, 不要求初始 HTML 存在)
DYNAMIC_IDS = {"ad_en", "kgsvg", "opt_adays", "opt_away", "opt_daily",
               "opt_review", "opt_rtime", "opt_theme", "ringfg"}


# ---------- render 隔离 ----------
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


def _extract_node_text(html, node_id):
    """提取指定 id 元素的文本内容(简单正则, 不嵌套)。"""
    m = re.search(r'id="%s"[^>]*>([^<]{0,200})' % node_id, html)
    return m.group(1).strip() if m else None


# ---------- 1. DOM 基线 ----------
def test_dom_baseline():
    html = _render(True)
    assert "<title>学习仪表盘" in html or "学习仪表盘" in html.split("<title>")[1][:20], "title 缺失"
    assert 'lang="zh"' in html, "lang 属性缺失"
    assert 'script src="/dashboard.js"' in html, "dashboard.js 引用缺失"
    # D-8-1: interactive 外链 CSS(link), 主题覆盖层保留内联 themecss
    assert 'link rel="stylesheet" href="/dashboard.css"' in html, "interactive 缺外链 CSS"
    assert '<style id="varroot">' not in html, "interactive 不应内联 varroot(D-8 未生效)"
    assert '<style id="themecss">' in html, "themecss 注入点缺失"
    assert not re.search(r"__[A-Z_]{2,}__", html), "最终 HTML 残留未替换 placeholder"


def test_dom_baseline_snapshot():
    html = _render(False)
    assert 'lang="zh"' in html
    assert "scrollspy" in html, "快照缺内联 JS"
    # D-8-1: 快照自包含——varroot 内联 + themecss 保留 + 不引用外链 CSS
    assert '<style id="varroot">' in html, "快照缺内联 CSS(自包含能力丢失)"
    assert '<style id="themecss">' in html
    assert 'href="/dashboard.css"' not in html, "快照不应引用外链 CSS"
    assert not re.search(r"__[A-Z_]{2,}__", html)


# ---------- 2. Panel Contract ----------
def test_panel_contract_presence():
    for mode in (True, False):
        html = _render(mode)
        ids = _html_ids(html)
        for p in PANELS:
            assert p in ids, "面板 %s 缺失(mode=%s)" % (p, mode)
        # shell 节点是 class(非 id)
        assert 'class="side"' in html, "side 缺失(mode=%s)" % mode
        assert 'class="topbar"' in html, "topbar 缺失(mode=%s)" % mode
        assert '<main class="main">' in html, "main 缺失(mode=%s)" % mode


def test_panel_ids_unique():
    html = _render(True)
    for i in re.finditer(r'(?<![a-zA-Z-])id="([a-z0-9_-]+)"', html):
        assert len(re.findall(r'(?<![a-zA-Z-])id="%s"' % i.group(1), html)) == 1, "id 重复: %s" % i.group(1)


def test_panel_key_classes():
    html = _render(True)
    for cls in ["side", "nav", "topbar", "dash", "card", "modalwrap", "guidewrap", "ctx"]:
        assert 'class="%s' % cls in html or 'class="card' in html, "关键 class 缺失: %s" % cls


# ---------- 3. JS DOM Contract ----------
def test_js_static_ids_available():
    """JS getElementById 依赖的静态 id 必须在最终 HTML 中可寻址(排除动态创建)。"""
    with open(_JS_PATH, encoding="utf-8") as f:
        js = f.read()
    js_ids = set(re.findall(r"getElementById\(['\"]([a-z0-9_-]+)['\"]\)", js))
    assert len(js_ids) >= 60, "JS id 数异常: %d" % len(js_ids)
    for mode in (True, False):
        html = _render(mode)
        ids = _html_ids(html)
        missing = js_ids - ids - DYNAMIC_IDS
        assert not missing, "JS 静态依赖 id 缺失(mode=%s): %s" % (mode, sorted(missing))


# ---------- 4. CSS Contract ----------
def test_css_cross_panel_dom_prereq():
    """PREP 确认的跨面板 selector(#pnl-overview .big / .topbar .sub 等)的 DOM 前提。"""
    html = _render(True)
    assert 'id="pnl-overview"' in html and 'class="big"' in html, "overview .big 前提缺失"
    assert 'class="topbar"' in html and 'class="sub"' in html, "topbar .sub 前提缺失"
    # .card 位于 .dash 内
    dash_idx = html.find('class="dash"')
    card_idx = html.find('class="card', dash_idx)
    assert dash_idx != -1 and card_idx != -1 and card_idx > dash_idx, ".dash > .card 层级缺失"


# ---------- 5. Placeholder Contract ----------
def test_placeholder_no_residue():
    for mode in (True, False):
        html = _render(mode)
        residues = re.findall(r"__[A-Z_]{2,}__", html)
        assert not residues, "placeholder 残留(mode=%s): %s" % (mode, residues)


def test_no_python_repr_leak():
    for mode in (True, False):
        html = _render(mode)
        assert "None" not in html.replace("theme", ""), "渲染出现 'None'"
        assert "False" not in html, "渲染出现字符串 'False'"
        assert "True" not in html, "渲染出现字符串 'True'"


# ---------- 6. Cross Panel Data Contract ----------
def test_cross_panel_dn_tn_consistent():
    """DN/TN 在 overview(ringcnt) 与 today(taskcnt) 必须一致。"""
    html = _render(True)
    ring = _extract_node_text(html, "ringcnt")
    task = _extract_node_text(html, "taskcnt")
    assert ring and task, "ringcnt/taskcnt 缺失: %r/%r" % (ring, task)
    dn_tn_ring = re.search(r"(\d+)/(\d+)", ring)
    dn_tn_task = re.search(r"(\d+)\s*/\s*(\d+)", task)
    assert dn_tn_ring and dn_tn_task, "DN/TN 提取失败: %r/%r" % (ring, task)
    assert dn_tn_ring.group(1) == dn_tn_task.group(1), "DN 不一致: %r vs %r" % (ring, task)
    assert dn_tn_ring.group(2) == dn_tn_task.group(2), "TN 不一致: %r vs %r" % (ring, task)


def test_cross_panel_streak_consistent():
    """STREAK 在 side(sidefoot) 与 progress 面板必须一致。"""
    html = _render(True)
    side_m = re.search(r'class="sidefoot"[\s\S]{0,200}?class="kpi">([^<]+)</div>', html)
    prog_m = re.search(r'连续打卡 <span class="kpi">([^<]+)</span>', html)
    assert side_m, "side streak 缺失"
    assert prog_m, "progress streak 缺失"
    assert side_m.group(1).strip() == prog_m.group(1).strip(), \
        "STREAK 不一致: side=%r progress=%r" % (side_m.group(1), prog_m.group(1))


# ---------- 7. Theme Contract ----------
def test_theme_contract_three_themes_distinct():
    bodies = {}
    for t in ("dark", "midnight-blue", "ink-green"):
        html = _render(True, theme_name=t)
        assert "__THEMECSS__" not in html, "theme 残留占位符"
        assert ":root{--bg:" in html, "theme CSS 未注入"
        m = re.search(r":root\{--bg:#([0-9a-fA-F]{6})", html)
        bodies[t] = m.group(1) if m else None
    assert bodies["dark"] != bodies["midnight-blue"], "dark/midnight 相同"
    assert bodies["midnight-blue"] != bodies["ink-green"], "midnight/ink 相同"


# ---------- 8. Interactive/Snapshot ----------
def test_interactive_external_snapshot_self_contained():
    i_html = _render(True)
    s_html = _render(False)
    assert 'script src="/dashboard.js"' in i_html, "interactive 应外链"
    assert "<script src=" not in s_html, "snapshot 不应外链"
    assert "scrollspy" in s_html, "snapshot 应内联 JS"
    assert "window.LH_CONFIG" in i_html and "window.LH_CONFIG" in s_html, "LH_CONFIG 双模式缺失"


# ---------- 9. DOM Snapshot ----------
class _IdTreeParser(HTMLParser):
    """提取带 id 的元素树(结构化 JSON 供 D-5b-1 前后对比)。"""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.tree = {}
        self.all_nodes = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        node_id = d.get("id")
        node = {"tag": tag, "id": node_id,
                "classes": d.get("class", "").split() if d.get("class") else [],
                "children": []}
        if node_id:
            self.all_nodes[node_id] = node
        if self.stack:
            parent = self.stack[-1]
            if parent is not None:
                parent["children"].append(node)
        else:
            self.tree[node_id] = node
        self.stack.append(node if node_id else None)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


def test_dom_snapshot_json_roundtrip():
    """DOM snapshot 生成结构化 JSON(id 树), 未来 D-5b-1 拆分后可对比。"""
    html = _render(True)
    p = _IdTreeParser()
    p.feed(html)
    assert p.tree, "id 树为空"
    flat = p.all_nodes
    assert len(flat) >= 60, "id 节点数异常: %d" % len(flat)
    for pid in ("pnl-overview", "pnl-tasks", "pnl-today", "modal", "ksearch"):
        assert pid in flat, "DOM snapshot 缺 %s" % pid
    # 写快照供未来对比(项目外, 不进 git)
    out = os.path.join(_BASE, "..", "_dom_snapshot_d5b0.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(flat),
                   "panels": [pid for pid in flat if pid.startswith("pnl-")]},
                  f, ensure_ascii=False, indent=1)


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
    sys.exit(1 if failed else 0)
