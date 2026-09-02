# -*- coding: utf-8 -*-
"""visual_regression/config.py —— 视觉回归统一配置（唯一配置源）。

所有 viewport / theme / browser / timeout / 截图路径 / Ready 条件集中于此，
禁止在脚本中硬编码。修改本文件即全局生效。

运行环境：anaconda3 python（playwright 1.62.0 + pillow 12.3.0 已装）。
"""
import os

# ---------------- 路径 ----------------
BASE = os.path.dirname(os.path.abspath(__file__))          # visual_regression/ 目录
PROJECT_ROOT = os.path.dirname(BASE)                        # learning/ 项目根
BASELINE_DIR = os.path.join(BASE, "baselines")              # 基线（进 git，视觉契约）
CURRENT_DIR = os.path.join(BASE, "current")                 # 本次截图（gitignore）
DIFF_DIR = os.path.join(BASE, "diff")                       # diff 图（gitignore）
BACKUP_DIR = os.path.join(BASE, ".backup")                  # 数据文件备份（gitignore）

# ---------------- 服务 ----------------
HOST = "127.0.0.1"
PORT0 = 8765                        # 与 config.py 一致；占用自动 +1 试 6 个
SERVER_TIMEOUT = 30                 # 服务启动等待（秒）
FETCH_TIMEOUT = 20000               # networkidle 等待（毫秒）

# ---------------- Viewport（用户指定验收尺寸） ----------------
VIEWPORTS = {
    "desktop": (1280, 800),
    "mobile": (390, 844),
    "tablet": (768, 1024),
}
DEVICE_SCALE_FACTOR = 1.0           # 固定，禁止变化

# ---------------- Theme（项目 3 个真实主题，全暗色无 light） ----------------
THEMES = ["dark", "midnight-blue", "ink-green"]
THEME_DEFAULT = "dark"

# ---------------- 页面 ----------------
PAGES = ["dashboard", "editor"]
PAGE_URLS = {"dashboard": "/", "editor": "/editor"}

# ---------------- 动画冻结注入（不修改生产 CSS） ----------------
ANIMATION_FREEZE_CSS = """
* { animation: none !important; transition: none !important; }
"""

# ---------------- Ready 条件（依据真实 DOM 实测确认，非猜测） ----------------
# 每项: (等待类型, 参数)。类型: selector=元素出现; networkidle=请求完成。
# dashboard 结构: 任务面板服务端内联 .task; 洞察面板初始"洞察计算中…"→fetch 后填充 .inscell
# editor 结构: textarea#ed; loadNote() 在 load 时 fetch /api/load_note 填充 #stat/#pv
DASHBOARD_READY = [
    ("selector", "#pnl-tasks .task"),        # 任务面板内联（服务端渲染，立即存在）
    ("selector", "#inswrap .inscell"),       # 洞察 fetch 完成（初始为"洞察计算中…"占位）
    ("networkidle", None),                   # 全部 9 个 /api/* 请求完成
]
EDITOR_READY = [
    ("selector", "#ed"),                     # 编辑器主体存在
    ("selector", "#stat"),                   # 状态栏（loadNote 填充）
    ("networkidle", None),                   # load_note fetch 完成
]
READY_CONDITIONS = {"dashboard": DASHBOARD_READY, "editor": EDITOR_READY}

# ---------------- 动态内容 Mask（截图时涂灰，不参与 diff） ----------------
# dashboard 顶部时钟 .clock 为服务端渲染时刻（如 23:50:01），跨运行必变 → mask。
# dashboard #daily-focus 元素依赖 /api/daily-focus（每 5 分钟 setInterval 重 fetch），
# 跨运行数据状态变化 → mask，避免内容动态影响视觉回归判定。
# editor 无动态元素（内容来自服务端注入）。
MASK_SELECTORS = {
    "dashboard": [".clock", "#daily-focus"],
    # Phase2-T01: editor 三处纯日历噪音(日期控件值/状态行/草稿标题)跨零点必变,
    # 掩蔽以消除每日伪回归; 结构存在性仍由 EDITOR_READY 断言。
    "editor": ["#date", "#stat", "#pv h1"],
}

# ---------------- 截图稳定参数 ----------------
POST_READY_DELAY_MS = 500             # ready 条件满足后再等 500ms 收尾渲染
STABILITY_ROUNDS = 3                  # 每组合连续截图次数（稳定性验证）
STABILITY_THRESHOLD = 0.05            # 稳定阈值：3 次互比像素变化比例 ≤ 5%（含微小反锯齿）

# ---------------- Pixel Diff ----------------
# 像素差异阈值：单像素通道差 ≥ 该值判定为"变化像素"
PIXEL_DIFF_THRESHOLD = 30
# 整体变化比例阈值：超过则 FAIL（视觉回归不通过）
DIFF_RATIO_THRESHOLD = 0.01           # 1%：允许反锯齿/字体渲染微差，禁止高阈值掩盖回归

# ---------------- 数据文件保护（服务会写盘） ----------------
# 测试启动服务前备份、结束后恢复，保证视觉测试不污染真实数据。
DATA_FILES_TO_PROTECT = [
    "tasks.json", "STATUS.json", "settings.json", "operations_log.json",
    "daily/knowledge.json", "daily/graph.json", "daily/analysis.json",
]

# ---------------- Baseline 元信息 ----------------
COMMIT_RECORD_FILE = os.path.join(BASELINE_DIR, "baseline_info.md")

# ---------------- 组合展开（页面 × 主题 × 视口） ----------------
def all_combos():
    """返回所有 (page, theme, viewport) 组合列表"""
    return [(p, t, v) for p in PAGES for t in THEMES for v in VIEWPORTS]

def combo_name(page, theme, viewport):
    """组合文件名片段: dashboard__dark__desktop"""
    return "%s__%s__%s" % (page, theme, viewport)

def shot_path(base_dir, page, theme, viewport):
    """组合截图完整路径"""
    return os.path.join(base_dir, page, combo_name(page, theme, viewport) + ".png")
