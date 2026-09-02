# -*- coding: utf-8 -*-
"""duration.py —— v1.8 模块A3: 非结构化耗时文本 -> 分钟数(纯标准库)

支持的写法(来自真实笔记语料):
  <=45min / ≤45min   约30分钟   ~1h   45-60min   1.5小时   20m   1-1.5h   90分钟

设计约定:
  - 区间取中值(45-60min -> 52): 预估本身就是模糊量, 中值是最诚实的点估计;
  - 必须带时间单位才认(防误伤 '第 1/56 天'、'2026-08-22'、'v0.2 三项');
  - 解析不出返回 None, 调用方自行决定是否落 est_minutes 字段。
"""
import re

# 小时类单位: h/ hour/ hours/ hr/ hrs / 小时 ; 其余(min/分钟/m)按分钟
_HOUR = r"(?:h(?:ou?r)?s?|小时)"
_MINS = r"(?:分(?:钟)?|min(?:ute)?s?|m)"      # 中文分/分钟与英文 min/m 同权

_RE_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-~～至到]\s*(\d+(?:\.\d+)?)\s*("
    + _HOUR + "|" + _MINS + ")(?![a-zA-Z])", re.I)
_RE_SINGLE = re.compile(
    r"[<=≤≤~～约大概将近]{0,2}\s*(\d+(?:\.\d+)?)\s*("
    + _HOUR + "|" + _MINS + ")(?![a-zA-Z])", re.I)


def _to_minutes(value, unit):
    u = unit.lower()
    if u.startswith("h") or "小时" in u:
        value *= 60.0
    return int(round(value))


def parse_duration(text):
    """从任意文本提取第一个可识别的时长, 返回分钟数(int)或 None。"""
    if not text:
        return None
    t = str(text)

    m = _RE_RANGE.search(t)                      # 区间优先: '45-60min' 若先做单值会只吃到 45
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        mid = (lo + hi) / 2.0
        return _to_minutes(mid, m.group(3))

    m = _RE_SINGLE.search(t)
    if m:
        return _to_minutes(float(m.group(1)), m.group(2))
    return None


def format_badge(minutes):
    """徽章文案: <60 显示 '⏱45m', >=60 显示 '⏱1.5h'(人读得懂优先)。"""
    if not minutes:
        return None
    minutes = int(minutes)
    if minutes >= 60 and minutes % 60 == 0:
        return "⏱%dh" % (minutes // 60)
    if minutes > 60:
        return "⏱%.1fh" % (minutes / 60.0)
    return "⏱%dm" % minutes
