# -*- coding: utf-8 -*-
"""nl_capture.py —— v1.9 C3: 自然语言快速捕获(纯正则+关键词, 零 NLP 依赖)

parse_quick_input("明天上午 45分钟 复习agent")
  -> {title:"复习agent", day:"tomorrow", window:"09-12", est_minutes:45, ...}

设计约定:
  - 解析出的片段会从原文剔除, 剩余部分即标题——『想到什么打什么』零格式要求;
  - 无法识别的词(如『尽快』)原样留在标题里, 绝不报错;
  - 字段越多 confidence 越高(>=3 high / 2 mid / 1 low), 供 UI 决定展示强度。
"""
import datetime
import io
import json
import os
import re

import duration

BASE = os.path.dirname(os.path.abspath(__file__))
KW_PATH = os.path.join(BASE, "tag_keywords.json")

_DAY_WORDS = [("今天", "today", 0), ("今日", "today", 0), ("明天", "tomorrow", 1),
              ("明日", "tomorrow", 1), ("后天", "dayafter", 2)]
_WINDOWS = [("清晨", "06-09"), ("早上", "06-09"), ("上午", "09-12"),
            ("中午", "12-14"), ("下午", "14-17"), ("傍晚", "17-20"),
            ("晚上", "20-24"), ("夜里", "20-24")]
_PRI_WORDS = [("p1", 1), ("p2", 2), ("p3", 3), ("紧急", 1), ("重要", 1), ("低优", 3)]


def _load_keywords():
    try:
        with open(KW_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_quick_input(text, today=None, keywords=None):
    """自然语言 -> 结构化任务草稿。永不抛错, 尽量多识别。"""
    today = today or datetime.date.today()
    raw = str(text or "").strip()
    out = {"title": raw, "day": None, "day_label": None, "window": None,
           "est_minutes": None, "priority": None, "tags": [],
           "review_count": None, "confidence": "low"}
    if not raw:
        return out
    rest = raw
    eaten = []                      # 已识别片段(用于剔出标题)

    def eat(m):
        eaten.append((m.start(), m.end()))

    # ---- 时间词 ----
    for w, key, off in _DAY_WORDS:
        m = re.search(w, rest)
        if m:
            out["day"] = key
            out["day_label"] = w
            eat(m)
            break
    else:
        for w, wd in (("周一", 0), ("周二", 1), ("周三", 2), ("周四", 3),
                      ("周五", 4), ("周六", 5), ("周日", 6), ("周天", 6)):
            m = re.search("下?" + w, rest)
            if m:
                delta = (wd - today.weekday()) % 7
                delta = delta if delta else 7          # 『周X』默认指未来的最近一个
                if m.group(0).startswith("下"):
                    delta += 7                         # 『下周X』再推一周
                d = today + datetime.timedelta(days=delta)
                out["day"] = d.isoformat()
                out["day_label"] = m.group(0)
                eat(m)
                break
        else:
            m = re.search(r"(\d{1,2})月(\d{1,2})日?", rest)
            if m:
                try:
                    d = datetime.date(today.year, int(m.group(1)), int(m.group(2)))
                    if d < today:
                        d = d.replace(year=today.year + 1)   # 已过期视为明年同日
                    out["day"] = d.isoformat()
                    out["day_label"] = m.group(0)
                    eat(m)
                except ValueError:
                    pass                          # 2月30日这类: 忽略不报错

    # ---- 时段词 ----
    for w, win in _WINDOWS:
        m = re.search(w, rest)
        if m:
            out["window"] = win
            eat(m)
            break
    else:
        m = re.search(r"(\d{1,2})[-~～到]\s*(\d{1,2})[点时]", rest)
        if m:
            out["window"] = "%02d-%02d" % (int(m.group(1)), int(m.group(2)))
            eat(m)

    # ---- 耗时(复用 A3 引擎) ----
    m = re.search(r"[≤<=~～约大概将近]{0,2}\s*\d+(?:\.\d+)?\s*(?:分钟|min|m|小时|h)(?!\w)",
                  rest, re.I)
    em = duration.parse_duration(rest)
    if em and m:
        out["est_minutes"] = em
        eat(m)

    # ---- 优先级 ----
    for w, p in _PRI_WORDS:
        m = re.search(re.escape(w), rest, re.I)
        if m:
            out["priority"] = p
            eat(m)
            break

    # ---- 复习标记: 文本提及复习/刷卡/回顾 + 数量张 ----
    # 为什么不限定相邻: 『复习 #项目工程 3张』中间隔着显式标签, 简单邻接会漏配
    if re.search(r"复习|刷卡|回顾", rest):
        m = re.search(r"(\d+)\s*张", rest)
        if m:
            out["review_count"] = max(1, min(50, int(m.group(1))))
            eat(m)

    # ---- 标签: 显式 #xxx 优先, 再按词库命中补足 ----
    for m in re.finditer(r"#([^\s#,]+)", rest):
        tg = m.group(1).strip()
        if tg and tg not in out["tags"]:
            out["tags"].append(tg)
        eat(m)
    kws = keywords if keywords is not None else _load_keywords()
    low = rest.lower()
    for tag, words in (kws.items() if isinstance(kws, dict) else []):
        if tag in out["tags"]:
            continue
        if any(str(w).lower() in low for w in (words or [])):
            out["tags"].append(tag)

    # ---- 标题: 剔除已识别区间后的剩余字符 ----
    keep = []
    last = 0
    for a, b in sorted(eaten):
        if a >= last:
            keep.append(raw[last:a])
            last = b
    keep.append(raw[last:])
    title = re.sub(r"\s{2,}", " ", "".join(keep)).strip(" ,，。;；-")
    out["title"] = title or raw

    n_fields = sum(1 for k in ("day", "est_minutes", "priority") if out.get(k)) \
        + (1 if out["tags"] else 0) + (1 if out["review_count"] else 0)
    out["confidence"] = "high" if n_fields >= 3 else ("mid" if n_fields == 2 else "low")
    return out
