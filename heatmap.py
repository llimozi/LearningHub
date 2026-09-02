# -*- coding: utf-8 -*-
"""heatmap.py —— 学习热力图与笔记扫描（v0.6 · 纯标准库）

公开 API:
  scan_daily(learning_dir, with_text=False)
      -> {date: {title, tags, chars, words, checkboxes, [_text]}}
  heatmap_payload(learning_dir, state, days=365, today=None)
      -> {"days":[{date,level,words,tasks}], "total_notes":n}

level 规则: 0=当日无笔记; 有笔记 1~4, 分数 = 非空白字符数/100 + 当日任务数, 每满3分升一档
"""
import os
import re
from datetime import date, timedelta

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def scan_daily(learning_dir, with_text=False):
    """扫描 daily/*.md: 标题(首行#)、tags: 行、非空白字数、checkbox 数"""
    daily_dir = os.path.join(learning_dir, "daily")
    out = {}
    if not os.path.isdir(daily_dir):
        return out
    for fn in os.listdir(daily_dir):
        m = _DATE_RE.match(fn)
        if not m:
            continue
        date_str = m.group(1)
        path = os.path.join(daily_dir, fn)
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
        except Exception:
            continue
        lines = text.splitlines()
        title = date_str
        if lines and lines[0].startswith("#"):
            title = lines[0].lstrip("# ").strip() or date_str
        tags = []
        for ln in lines[1:4]:                      # 只看文件头前几行
            tm = re.match(r"^tags\s*:\s*(.+)$", ln.strip(), re.I)
            if tm:
                tags = [t.strip() for t in tm.group(1).split(",") if t.strip()]
                break
        chars = len(re.sub(r"\s", "", text))
        boxes = len(re.findall(r"^\s*-\s+\[( |x|X)\]", text, re.M))
        rec = {"title": title, "tags": tags, "chars": chars,
               "words": chars, "checkboxes": boxes}
        if with_text:
            rec["_text"] = text                    # 下划线开头: /api/notes 输出时会剔除
        out[date_str] = rec
    return out


def heatmap_payload(learning_dir, state, days=365, today=None):
    """生成近 N 天热力图数据: 无笔记=0级, 有笔记按 分数 分档 1~4"""
    daily = scan_daily(learning_dir)
    days_map = state.get("days", {})
    today = today or date.today()
    items = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        info = daily.get(d)
        tasks = len(days_map.get(d, []))
        words = info["chars"] if info else 0
        if not info:
            level = 0
        else:
            score = words / 100.0 + tasks
            level = min(4, 1 + int(score // 3))
        items.append({"date": d, "level": level, "words": words, "tasks": tasks})
    return {"days": items, "total_notes": len(daily)}
