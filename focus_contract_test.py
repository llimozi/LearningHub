# -*- coding: utf-8 -*-
"""focus_contract_test.py —— 键盘焦点环契约 (v1.0 · 纯标准库)

背景（2026-08-31 审计, refactor_phase2/49）：
  8 个 topbar/工具条按钮（#btn-capture/#btn-note/#btnweek/#btn-batchmode/
  #btn-cmdk-top/#btn-backfill/#pnl-review .btn-mini/#pnl-help .btn）在
  :focus-visible 时无任何可见焦点指示——浏览器实测三主题 box-shadow
  无聚焦环（ghost 组 = none, 其余 = 基础投影）。
  根因：文件更早处 `.btn-ghost{box-shadow:none!important}` 等 !important
  规则压掉了 `.btn:focus-visible` 的聚焦环（L751 环规则无 !important 无法反压）。

契约（关系型，非计数）：
  1. 存在同时覆盖 .btn/.btn-mini/.btn-ghost/.btn-good 四种变体的
     :focus-visible 规则（选择器关系）；
  2. 该规则声明 box-shadow:var(--focus-ring) 且带 !important（反压能力）；
  3. 该规则必须位于所有 box-shadow:none!important 按钮规则之后（级联顺序）；
  4. 通过 1+2+3 蕴含「四种变体的键盘焦点环在任何后续覆盖下不被压掉」。

备注：:focus-visible 的浏览器语义行为由视觉验证覆盖（本套件为静态防线）。
"""
import io
import os
import re
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_BASE, "templates", "dashboard.css")
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")

_VARIANTS = [".btn-mini:focus-visible", ".btn-ghost:focus-visible",
             ".btn-good:focus-visible"]


def _css():
    with io.open(_CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _rule_positions(css):
    """返回 [(selector_normalized, body_normalized, end_index)] 按出现顺序。"""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(m.group(1).split())
        body = " ".join(m.group(2).split())
        if sel:
            out.append((sel, body, m.end()))
    return out


def _find_focus_rule(rules):
    """定位统一聚焦环规则: 选择器含 .btn 与 :focus-visible 且覆盖全部变体,
    规则体含 box-shadow:var(--focus-ring)!important。"""
    for sel, body, pos in rules:
        if ":focus-visible" not in sel or ".btn" not in sel:
            continue
        if not all(v in sel for v in _VARIANTS):
            continue
        if re.search(r"box-shadow\s*:\s*var\(--focus-ring\)\s*!important", body):
            return sel, body, pos
    return None


def _none_important_positions(rules):
    """所有把按钮家族 box-shadow 置 none!important 的规则位置。"""
    out = []
    for sel, body, pos in rules:
        if not any(k in sel for k in (".btn", ".btn-mini", ".btn-ghost",
                                      ".btn-good", ".btn-mini", ".btn-capture",
                                      "#btnweek", "#btn-note")):
            continue
        if "box-shadow:none!important" in body:
            out.append((sel, pos))
    return out


def test_unified_focus_ring_rule_exists_and_wins_cascade():
    css = _css()
    rules = _rule_positions(css)
    focus = _find_focus_rule(rules)
    assert focus, (
        "缺统一聚焦环规则: 须同时覆盖 .btn/.btn-mini/.btn-ghost/.btn-good 的 "
        ":focus-visible 且声明 box-shadow:var(--focus-ring)!important "
        "(2026-08-31 修复, 见 refactor_phase2/49)")
    _sel, _body, focus_pos = focus
    # 契约 3: 聚焦环规则必须位于所有 box-shadow:none!important 按钮规则之后
    late_none = [s for s, p in _none_important_positions(rules) if p > focus_pos]
    assert not late_none, (
        "聚焦环规则之后仍有 box-shadow:none!important 按钮规则(%s) —— "
        "焦点环将被压掉" % late_none)


def test_focus_ring_rule_declares_important():
    css = _css()
    focus = _find_focus_rule(_rule_positions(css))
    assert focus, "缺统一聚焦环规则(见 test_unified_focus_ring_rule_exists_and_wins_cascade)"
    _sel, body, _pos = focus
    assert "!important" in body, "聚焦环规则必须带 !important 以反压 ghost 的 none!important"
    assert "var(--focus-ring)" in body, "聚焦环规则必须使用既有 --focus-ring token"


def test_kbmode_act_reveal_wiring():
    """J/K 键盘导航行的动作按钮揭示契约（2026-08-31 修复）:
    浏览器实测按 j 后 kb-focus 行的 .hact 为 display:none——
    CSS 揭示规则 body.kbmode .task.kb-focus .hact 存在, 但 JS 从未添加
    kbmode 类(死规则)。契约: CSS 规则与 JS 接线必须同时存在(关系型)。"""
    css = _css()
    with io.open(_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()
    assert re.search(r"body\.kbmode\s+\.task\.kb-focus\s+\.hact", css), \
        "CSS 缺 body.kbmode 揭示规则(动作按钮将仅悬停可见)"
    assert re.search(r"classList\.add\(['\"]kbmode['\"]\)", js), \
        "JS 未接线: 键盘导航(moveFocus)必须添加 body.kbmode, 否则规则空挂"


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
