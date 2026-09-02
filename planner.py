# -*- coding: utf-8 -*-
"""planner.py —— 自适应规划引擎（v0.3 · 纯标准库）

公开 API（build_dashboard.py 只调用这些）:
  append_history(state, date, total, done, keep=30) -> dict
  get_stats(state)                -> {"avg7","avg30","max_streak","days"}
  detect_fatigue(state)           -> {"active","since","reason"}
  is_fatigued(state)              -> bool
  normalize_priorities(state)     -> int
  sort_for_defer(tasks)           -> list
  fatigue_split(undone, fatigued) -> {"move","defer2","drop"}
  lin_slope(ys)                   -> float
  predict_tomorrow(state)         -> {"predicted","avg7_done","slope","clamped","cap","note"}
  finalize_day(state, date)       -> {"history","fatigue","stats","tomorrow"}

阈值: 连续3天rate<0.5触发疲劳; 单日rate>=0.8解除; 斜率限±0.3; history保留30天
"""
import datetime

FATIGUE_LOW = 0.5
FATIGUE_TRIGGER_RUN = 3
RELEASE_RATE = 0.8
SLOPE_LIMIT = 0.3
HISTORY_KEEP = 30
DEFAULT_PRIORITY = 2


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _rate(rec):
    t = rec.get("total", 0)
    if "rate" in rec:
        return rec["rate"]
    return (rec.get("done", 0) / t) if t else 0.0


def append_history(state, date, total, done, keep=HISTORY_KEEP):
    """追加(或更新同日)一条历史记录, 按日期排序并只保留最近 keep 天。
    Phase E-B: total=0(空计划日)不追加——「没排任务」≠「0% 完成」,
    旧行为记 rate=0.0 会污染自适应减负与疲劳判定(E-A 审计实证 08-23)。"""
    if not total:
        return None                                       # 空日跳过, 不进 rate 序列
    rec = {"date": date, "total": total, "done": done,
           "rate": round(done / total, 4) if total else 0.0}
    hist = state.setdefault("history", [])
    for i, old in enumerate(hist):
        if old.get("date") == date:
            hist[i] = rec
            break
    else:
        hist.append(rec)
    hist.sort(key=lambda x: x.get("date", ""))
    if len(hist) > keep:
        del hist[:-keep]
    return rec


def get_stats(state):
    hist = state.get("history", [])
    rates = [_rate(r) for r in hist]
    streak = best = 0
    for r in rates:
        streak = streak + 1 if r >= RELEASE_RATE else 0
        best = max(best, streak)
    return {"avg7": round(_mean(rates[-7:]), 4),
            "avg30": round(_mean(rates[-30:]), 4),
            "max_streak": best, "days": len(hist)}


def detect_fatigue(state):
    """全量重放 history 的状态机: >=0.8 解除并清连击; <0.5 计连击, 满3触发; 中间值仅打断连击"""
    hist = state.get("history", [])
    active = False
    low_run = 0
    since = None
    reason = ""
    for rec in hist:
        r = _rate(rec)
        if r >= RELEASE_RATE:
            active = False
            low_run = 0
            since = None
            reason = ""
        elif r < FATIGUE_LOW:
            low_run += 1
            if low_run >= FATIGUE_TRIGGER_RUN and not active:
                active = True
                since = rec.get("date")
                reason = "连续%d天完成率<50%%" % low_run
        else:
            low_run = 0
    f = {"active": active, "since": since, "reason": reason}
    state["fatigue"] = f
    return f


def is_fatigued(state):
    return bool(detect_fatigue(state).get("active"))


def normalize_priorities(state):
    """给缺 priority 字段的任务补默认值, 返回补齐条数"""
    n = 0
    for bucket in state.get("days", {}).values():
        for t in bucket:
            if "priority" not in t:
                t["priority"] = DEFAULT_PRIORITY
                n += 1
    return n


def sort_for_defer(tasks):
    """高优先级在前(稳定排序, 同级保持原顺序)"""
    return sorted(tasks, key=lambda t: t.get("priority", DEFAULT_PRIORITY))


def fatigue_split(undone, fatigued):
    """疲劳时: p1 滚明天, p2 延后2天, p3 丢弃; 非疲劳全部滚"""
    if not fatigued:
        return {"move": list(undone), "defer2": [], "drop": []}
    return {
        "move": [t for t in undone if t.get("priority", DEFAULT_PRIORITY) == 1],
        "defer2": [t for t in undone if t.get("priority", DEFAULT_PRIORITY) == 2],
        "drop": [t for t in undone if t.get("priority", DEFAULT_PRIORITY) == 3],
    }


def lin_slope(ys):
    """最小二乘斜率, x=0..n-1; 少于2点返回0"""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(range(n), ys))
    sxx = sum((x - mx) ** 2 for x in range(n))
    return sxy / sxx if sxx else 0.0


def predict_tomorrow(state):
    """predicted = round(近7日均完成数 * (1+斜率)), 斜率限±0.3; 疲劳时受 cap=max(3,均完成*0.8) 约束"""
    hist = state.get("history", [])[-7:]
    if not hist:
        return {"predicted": 3, "avg7_done": 0.0, "slope": 0.0,
                "clamped": False, "cap": None, "note": "无历史, 默认3条"}
    avg7_done = _mean([r.get("done", 0) for r in hist])
    raw_slope = lin_slope([_rate(r) for r in hist])
    slope = max(-SLOPE_LIMIT, min(SLOPE_LIMIT, raw_slope))
    clamped = abs(raw_slope) > SLOPE_LIMIT
    raw = round(avg7_done * (1 + slope))
    predicted = max(1, raw)
    cap = None
    note = ""
    if is_fatigued(state):
        cap = max(3, round(avg7_done * 0.8))
        if predicted > cap:
            predicted = cap
            note = "疲劳模式上限生效"
    return {"predicted": predicted, "avg7_done": round(avg7_done, 2),
            "slope": round(slope, 3), "clamped": clamped, "cap": cap, "note": note}


def finalize_day(state, date):
    """收尾编排: 记历史 -> 判疲劳 -> 给统计与明日预测(不做任务移动, 移动归 rollover)"""
    bucket = state.get("days", {}).get(date, [])
    total = len(bucket)
    done = sum(1 for t in bucket if t.get("done"))
    rec = append_history(state, date, total, done)
    fatigue = detect_fatigue(state)
    return {"history": rec, "fatigue": fatigue,
            "stats": get_stats(state), "tomorrow": predict_tomorrow(state)}
