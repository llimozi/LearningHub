# -*- coding: utf-8 -*-
r"""theme.py —— 主题系统 (v1.3 · 纯标准库, CSS 变量 + 末位覆盖层)

三套暗色主题(v1.3 规格): dark=深空灰(现行配色) / midnight-blue=午夜蓝 / ink-green=墨绿。

实现策略——**末位覆盖层**而非改写原样式表:
  dashboard.html 与 editor.html 的既有 <style> 保持原样;
  在其后追加「:root 变量块 + 带权重的覆盖规则」(只消费变量),
  同等特异性下后者胜出 → 零侵入、可回滚、编辑器与仪表盘共用同一变量根。
切换即时生效: 设置页 changeTheme() 拉取 /api/theme 的覆盖层文本,
原地替换 <style id="themecss"> 内容并持久化 settings.theme, 不刷新页面。

公开 API:
  THEMES / DEFAULT_THEME / REQUIRED_VARS / CSS_VAR_ORDER
  get_theme(name) -> spec(未知回退默认)
  theme_root_css(name) -> ":root{--bg:...;...}"   (变量顺序 = CSS_VAR_ORDER, 稳定可测)
  override_css(name, target="dashboard"|"editor") -> 完整注入文本(root+该端覆盖规则)
  set_theme(learning_dir, name) -> 归一化主题名并持久化(非法回退默认)
"""
import json
import os

import settings as settings_mod

DEFAULT_THEME = "dark"

# 必备变量集(顺序即输出顺序, 稳定可测)
CSS_VAR_ORDER = ["--bg", "--card", "--card2", "--hover", "--input",
                 "--border", "--border2", "--body", "--text", "--dim",
                 "--accent", "--accent-hov", "--good", "--bad", "--warn",
                 "--tag-bg", "--pink"]
REQUIRED_VARS = tuple(CSS_VAR_ORDER)

THEMES = {
    "dark": {
        "label": "深空灰",
        "vars": {
            "--bg": "#08090A", "--card": "#0F1011", "--card2": "#161718",
            "--hover": "#1C1D1E", "--input": "#050607",
            "--border": "#1F2022", "--border2": "#2A2B2E",
            "--body": "#D4D4D4", "--text": "#E8E8E8", "--dim": "#8B8B8B",
            "--accent": "#5E6AD2", "--accent-hov": "#7B83E8",
            "--good": "#4CB782", "--bad": "#EB5757", "--warn": "#F2994A",
            "--tag-bg": "#1A1B1E", "--pink": "#B084D9",
        },
    },
    "midnight-blue": {
        "label": "午夜蓝",
        "vars": {
            "--bg": "#07090F", "--card": "#0D1018", "--card2": "#141824",
            "--hover": "#1A1F2E", "--input": "#05070C",
            "--border": "#1A1F2C", "--border2": "#252B3D",
            "--body": "#C8CDD8", "--text": "#DDE2EE", "--dim": "#7A8299",
            "--accent": "#5B7FC9", "--accent-hov": "#7A9ADB",
            "--good": "#48A878", "--bad": "#D96068", "--warn": "#D99A4E",
            "--tag-bg": "#141826", "--pink": "#9B7FC0",
        },
    },
    "ink-green": {
        "label": "墨绿",
        "vars": {
            "--bg": "#070A08", "--card": "#0D110E", "--card2": "#141A16",
            "--hover": "#1A211C", "--input": "#050706",
            "--border": "#1A201C", "--border2": "#252D28",
            "--body": "#C8D0CA", "--text": "#DDE5DE", "--dim": "#7A8880",
            "--accent": "#5A9E7C", "--accent-hov": "#7AB898",
            "--good": "#48A878", "--bad": "#C96B5E", "--warn": "#C9A05A",
            "--tag-bg": "#141A16", "--pink": "#9B8A7F",
        },
    },
}


def get_theme(name):
    """取主题规格; 未知/空值一律回退默认(永不抛错)"""
    key = str(name or "").strip().lower()
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def theme_root_css(name):
    """':root{--bg:#..;--card:#..;...}' —— 变量输出顺序恒等于 CSS_VAR_ORDER"""
    spec = get_theme(name)
    parts = ["%s:%s" % (v, spec["vars"][v]) for v in CSS_VAR_ORDER]
    return ":root{" + ";".join(parts) + "}"


_DASH_RULES = """
/* ---- v1.3 主题覆盖层(dashboard): 只消费上方变量, 末位生效 ---- */
/* DASH-21/22 保留(DD-02 方案 A, Batch 2C-2): .modal 非等价项——dashboard.css 降级段
   L1368-1371 用 background:var(--card2)、L1361-1364 用 border-color:
   var(--color-border-subtle) 高优先级接管(浮层面板语义),
   覆盖层 var(--card)/var(--border2) 维持实体卡片色(稳定生产语义) */
.modal{background:var(--card)!important;border-color:var(--border2)!important}
"""



def override_css(name, target="dashboard"):
    """完整注入文本: :root 变量 + 对应端的带权重覆盖规则"""
    root = theme_root_css(name)
    if target == "editor":
        # Batch 2B-1: editor 覆盖层全部迁入 editor.html 原生 var 化, 注入侧仅 :root
        return root
    return root + "\n" + _DASH_RULES


def set_theme(learning_dir, name):
    """归一化并持久化主题选择; 非法名回退默认。返回归一化后的名字。"""
    key = str(name or "").strip().lower()
    if key not in THEMES:
        key = DEFAULT_THEME
    cfg = settings_mod.load_settings(learning_dir)
    if cfg.get("theme") != key:
        cfg["theme"] = key
        settings_mod.save_settings(learning_dir, cfg)
    return key


def current_theme(learning_dir):
    """读当前主题名(归一化, 容错)"""
    cfg = settings_mod.load_settings(learning_dir)
    name = str(cfg.get("theme", DEFAULT_THEME)).strip().lower()
    return name if name in THEMES else DEFAULT_THEME
