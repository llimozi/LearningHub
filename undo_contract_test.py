# -*- coding: utf-8 -*-
"""undo_contract_test.py —— 撤销可发现性契约 (v1.0 · 纯标准库)

背景（Phase3-T01, 2026-08-31）：
  撤销能力此前仅可通过 Ctrl+Z 触达, 无任何可见 UI 提示, 用户不知道
  破坏性操作可撤销。本任务新增「撤销 toast」可发现机制。

契约（关系型, 防死规则/防脱节）：
  1. lhToastUndo 存在(内嵌「撤销」按钮的 toast 实现);
  2. checkUndoOffer 存在(reload 后从 sessionStorage 读取并弹出撤销 toast);
  3. batchDo 对可撤销操作(delete/done/snooze/priority)写 lh_undo 到 sessionStorage;
  4. window.lhUndo 暴露(撤销按钮点击后的真实撤销入口);
  5. CSS 有 .tundo:focus-visible 聚焦环(键盘可达性);
  6. .tundo 按钮 pointer-events 可用(可点击)。

任一侧缺失 → 撤销可发现性断裂(或死规则)。
"""
import io
import os
import re
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_JS_PATH = os.path.join(_BASE, "templates", "dashboard.js")
_CSS_PATH = os.path.join(_BASE, "templates", "dashboard.css")


def _js():
    with io.open(_JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _css():
    with io.open(_CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_toast_undo_fn_and_wiring_exist():
    js = _js()
    # 1. 撤销 toast 实现(含「撤销」按钮注入)
    assert re.search(r"function\s+lhToastUndo\s*\(", js), "缺 lhToastUndo 函数"
    assert 'class="tundo"' in js, "lhToastUndo 未注入 .tundo 撤销按钮"
    # 2. reload 后检查器
    assert re.search(r"function\s+checkUndoOffer\s*\(", js), "缺 checkUndoOffer"
    assert re.search(r"sessionStorage\.getItem\(['\"]lh_undo['\"]\)", js), \
        "checkUndoOffer 未读 lh_undo"
    # 3. 全局撤销入口暴露
    assert "window.lhUndo = doUndo" in js, "缺 window.lhUndo 暴露"


def test_batch_undoable_actions_write_session():
    js = _js()
    # batchDo 对可撤销操作必须写 lh_undo 到 sessionStorage
    m = re.search(r"function\s+batchDo\s*\([^)]*\)\s*\{(?:[\s\S]*?)setItem\(['\"]lh_undo['\"]", js)
    assert m, "batchDo 未对可撤销操作写 lh_undo 到 sessionStorage"
    # 可撤销操作集合
    assert "'delete'" in js and "'done'" in js and "'snooze'" in js and "'priority'" in js, \
        "batchDo 可撤销操作集合不完整(delete/done/snooze/priority)"


def test_undo_button_focus_and_click_css():
    js = _js()
    css = _css()
    # CSS 聚焦环
    assert re.search(r"\.tundo:focus-visible\s*\{[^}]*var\(--focus-ring\)", css), \
        "缺 .tundo:focus-visible 聚焦环(键盘不可达)"
    # 容器 has-undo → pointer-events:auto(撤销按钮可点击/可聚焦)
    assert re.search(r"#lhtoast\.has-undo\s*\{[^}]*pointer-events:\s*auto", css), \
        "缺 #lhtoast.has-undo pointer-events:auto(撤销按钮不可点)"
    # a11y: aria-live 播报 + aria-label + 按钮 tabIndex(聚焦性)
    assert "setAttribute('aria-live', 'polite')" in js, \
        "缺 aria-live=polite(读屏无法播报可撤销)"
    assert 'aria-label=' in js, "缺撤销按钮 aria-label"
    # 关系: has-undo 类在 lhToastUndo 中设置且 clear 中移除
    assert "classList.add('has-undo')" in js and "classList.remove('has-undo')" in js, \
        "has-undo 类添加/移除不配对(撤销容器可点状态管理断裂)"
    # 键盘可达: 撤销按钮自动聚焦(操作后 reload 焦点在 body, 聚焦此按钮使键盘可用)
    assert re.search(r"undoBtn\.focus\(\)", js), \
        "缺撤销按钮自动聚焦(键盘用户无法到达撤销入口)"


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
