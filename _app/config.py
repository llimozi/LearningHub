# -*- coding: utf-8 -*-
"""config.py —— 配置与模块级常量（原 build_dashboard.py 全局状态收拢, Phase 2.1）。

保持原语义: 所有常量在模块加载时计算, 与旧 build_dashboard.py 行为一致。
"""
import os
import re
import sys
import datetime

import paths

# v1.4 打包态关键改造: 源码态=脚本目录; PyInstaller 单文件态=exe 所在目录。
# 若继续用 __file__, 数据会写进 _MEIxxxx 临时解包目录并随退出消失(见 paths.py)。
BASE = paths.app_base()
TASKS_FILE = os.path.join(BASE, "tasks.json")
TODAY = datetime.date.today().isoformat()
PORT0 = 8765                                            # 默认端口(占用自动 +1 试 6 个)
_MAX_POST_BYTES = 10 * 1024 * 1024                      # 10MB: 写操作单次请求体上限(防 OOM)

# ---------------- STATUS.json 辅助(v1.0: last_open_ts 供回归提醒判断) ----------------
STATUS_FILE = os.path.join(BASE, "STATUS.json")

# ---------------- 撤销操作日志 ----------------
OPS_FILE = os.path.join(BASE, "operations_log.json")

# ---------------- 四线并行学习计划(plan.json) ----------------
# 数据源与 STATUS.json 同规范(utf-8-sig); A 线总进度由 STATUS.json total_percent 派生, 本文件不重复存储。
PLAN_FILE = os.path.join(BASE, "plan.json")

# ---------------- 任务 id 白名单(v1.4: 防注入, safe_task 用) ----------------
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# ---------------- v1.3 空状态插画(内联 SVG 线稿, 跟随主题色) ----------------
EMPTY_SVG = {
    "notebook": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" '
                 'stroke-width="2" stroke-linecap="round">'
                 '<rect x="28" y="12" width="64" height="66" rx="8" stroke="var(--color-accent)"/>'
                 '<line x1="40" y1="30" x2="80" y2="30"/><line x1="40" y1="42" x2="72" y2="42"/>'
                 '<line x1="40" y1="54" x2="76" y2="54"/>'
                 '<circle cx="88" cy="70" r="14" fill="var(--color-bg)" stroke="var(--color-state-success)"/>'
                 '<path d="M82 70 l4 4 l8 -8" stroke="var(--color-state-success)"/></svg>'),
    "graph": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2">'
              '<circle cx="35" cy="30" r="8" stroke="var(--color-accent)"/>'
              '<circle cx="80" cy="25" r="6" stroke="var(--color-text-muted)"/>'
              '<circle cx="60" cy="62" r="9" stroke="var(--color-state-success)"/>'
              '<path d="M42 34 L54 55 M73 30 L64 54 M86 30 L88 44" stroke="var(--color-border-strong)"/>'
              '<circle cx="98" cy="60" r="5" stroke="var(--color-text-muted)" stroke-dasharray="3 3"/></svg>'),
    "check": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2">'
              '<circle cx="60" cy="42" r="26" stroke="var(--color-state-success)"/>'
              '<path d="M48 42 l8 8 l16 -16" stroke="var(--color-state-success)" stroke-linecap="round"/>'
              '<path d="M30 76 h60" stroke="var(--color-border-strong)" stroke-linecap="round"/></svg>'),
    "sprout": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2">'
               '<path d="M60 74 V46" stroke="var(--color-state-success)"/>'
               '<path d="M60 52 C60 38 48 34 38 34 C38 46 48 52 60 52" stroke="var(--color-accent)"/>'
               '<path d="M60 46 C60 34 70 30 80 30 C80 42 72 46 60 46" stroke="var(--color-state-success)"/>'
               '<path d="M42 78 h36" stroke="var(--color-border-strong)" stroke-linecap="round"/></svg>'),
    "doc": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M38 12 h32 l14 14 v52 h-46 z" stroke="var(--color-accent)"/>'
            '<path d="M70 12 v14 h14" stroke="var(--color-accent)"/>'
            '<line x1="46" y1="40" x2="76" y2="40"/><line x1="46" y1="52" x2="70" y2="52"/>'
            '<line x1="46" y1="64" x2="64" y2="64" stroke="var(--color-text-muted)"/></svg>'),
    "compass": ('<svg viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2">'
                '<circle cx="60" cy="45" r="28" stroke="var(--color-accent)"/>'
                '<path d="M72 34 L64 52 L48 56 L56 38 Z" fill="var(--color-accent)" stroke="none"/>'
                '<circle cx="60" cy="45" r="3" fill="var(--color-bg)"/></svg>'),
}

__all__ = [
    "BASE", "TASKS_FILE", "TODAY", "PORT0", "_MAX_POST_BYTES",
    "STATUS_FILE", "OPS_FILE", "PLAN_FILE", "_SAFE_TASK_ID_RE", "EMPTY_SVG",
]
