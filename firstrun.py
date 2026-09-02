# -*- coding: utf-8 -*-
r"""firstrun.py —— 首次运行向导后端 (v1.4 · 纯标准库)

规格适配(如实): 原规格「检测 data/ 不存在则创建默认结构」——本项目数据形态是
learning 根散文件 + daily\ 目录, 故核心结构 = tasks.json / settings.json /
STATUS.json / daily\。缺什么建什么; 已存在的一律不覆盖(用户数据神圣)。

「欢迎页→设置学习方向→生成初始八周路线图」三步:
  欢迎与分步交互由仪表盘既有的 guide_done 三步引导浮层承担(v1.3 资产复用);
  本模块提供后端两件套:
    ensure_workspace(dir)          缺失核心结构初始化(幂等, 二跑零新建)
    generate_roadmap(direction,…)  生成含方向名的八周路线图骨架 ROADMAP.md
                                   (周一锚定日期、阶段总览/当前复习队列标题与
                                   build_dashboard.section() 解析器兼容;
                                   已存在跳过, force=True 才重写)

公开 API:
  ensure_workspace(learning_dir) -> {created:[...], existed:bool}
  generate_roadmap(direction, learning_dir, today=None, force=False)
      -> 路径 | None(已存在且未强制)
"""
import os
import json
import datetime

import settings as settings_mod

CORE_FILES = ("tasks.json", "settings.json", "STATUS.json")


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _default_status(today):
    """STATUS 总览骨架: 与 dashboard 渲染字段一一对应"""
    return {
        "updated": today.isoformat(),
        "total_percent": 0,
        "day": 1,
        "total_days": 56,
        "deadline": (today + datetime.timedelta(days=55)).isoformat(),
        "current_week": "W0 · 环境确认与首次配置",
        "streak": 0,
        "next_review": "暂无——开始学习后自动生成",
        "subjects": [
            {"name": "主线·" + "待向导填写", "percent": 0, "state": "pending"},
        ],
    }


def ensure_workspace(learning_dir, today=None):
    """缺失核心结构初始化: 只建缺的, 绝不覆盖已有文件/目录。"""
    today = today or datetime.date.today()
    created = []
    for name in CORE_FILES:
        p = os.path.join(learning_dir, name)
        if not os.path.exists(p):
            if name == "settings.json":
                settings_mod.ensure_settings(learning_dir)   # 统一走设置中心默认模板
            elif name == "tasks.json":
                _write_json(p, {"version": 3, "days": {}, "history": [],
                                "fatigue": {}, "log": []})
            else:
                _write_json(p, _default_status(today))
            created.append(name)
    daily = os.path.join(learning_dir, "daily")
    if not os.path.isdir(daily):
        os.makedirs(daily, exist_ok=True)
        created.append("daily")
    return {"created": created,
            "existed": len(created) == 0}


# ---------------- 八周路线图骨架 ----------------
_WEEK_THEMES = (
    ("W0", "环境确认 · 工具链就位", "跑通本地环境；完成首篇笔记"),
    ("W1", "{dir} · 入门基线", "核心概念过一遍；每日一篇笔记+自测一题"),
    ("W2", "{dir} · 动手深化", "完成第一个可运行的小项目切片"),
    ("W3", "{dir} · 进阶专题", "攻克两个进阶专题；建立概念网络"),
    ("W4", "{dir} · 集成实战", "把前三周产出集成为完整作品"),
    ("W5", "桌面化冲刺 · 常驻化", "托盘常驻 + 本地面板（对接已交付的 v1.0 能力）"),
    ("W6", "桌面化冲刺 · 打包演练", "裸打包踩坑：体积/杀软误报/资源路径"),
    ("W7", "验收与复盘", "总验收清单过一遍；沉淀复盘报告"),
)


def _monday_of(today):
    return today - datetime.timedelta(days=today.weekday())


def _roadmap_markdown(direction, start):
    lines = ["# 学习路线图 · %s（八周）" % direction, ""]
    lines.append("> 由首次运行向导生成于 %s · 起始周一 %s · 可自由编辑, 系统只读取标题结构"
                 % (datetime.datetime.now().isoformat(timespec="seconds"), start.isoformat()))
    lines += ["", "## 阶段总览", "",
              "| 周次 | 起始日期 | 主题 | 里程碑 | 完成 |",
              "|---|---|---|---|---|"]
    for i, (wk, theme, milestone) in enumerate(_WEEK_THEMES):
        d = (start + datetime.timedelta(days=7 * i)).isoformat()
        theme = theme.replace("{dir}", direction)
        lines.append("| %s | %s | %s | %s | ☐ |" % (wk, d, theme, milestone))
    lines += ["", "## 当前复习队列", "", "- [ ] D+1 自测：写下今天学的三个关键词并口述其含义",
              "- [ ] D+2 自测：不看笔记复述昨天的一个完整流程",
              "", "> 提示：以上两条为间隔重复起点，系统会按遗忘曲线自动安排后续复习。",
              "", "## 自测题库（随笔记持续追加）", "", "- （占位：每篇笔记留一道口述自测题）", ""]
    return "\n".join(lines)


def generate_roadmap(direction, learning_dir, today=None, force=False):
    """生成八周路线图骨架到 ROADMAP.md。
    已存在且未 force -> 返回 None(用户手笔神圣); force=True 才整体重写。"""
    direction = str(direction or "").strip()
    if not direction:
        raise ValueError("direction 不能为空")
    today = today or datetime.date.today()
    start = _monday_of(today)
    rp = os.path.join(learning_dir, "ROADMAP.md")
    if os.path.exists(rp) and not force:
        return None
    with open(rp, "w", encoding="utf-8-sig") as f:
        f.write(_roadmap_markdown(direction, start))
    return rp
