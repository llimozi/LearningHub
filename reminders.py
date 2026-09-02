# -*- coding: utf-8 -*-
"""reminders.py —— 本地通知提醒引擎 (v1.0 · 纯标准库)

设计原则:
  1. 判定与文案全部是纯函数: 时间(now)、数据(tasks/卡片/fired)都由参数注入,
     单测用 2099 年假时刻即可覆盖全部分支, 与真实系统时间解耦。
  2. 文案绝不写死: 任务文本取自 tasks.json 今日桶, 知识点名取自 analyzer
     复习卡片(需复习态), 天数/条数实时计算——改数据文案立刻跟着变。
  3. 防重弹: 命中即把键记入 fired[{日期: [键]}], 同日不再弹;
     跨天自动清理(默认保留7天), 记账随 settings.json 持久化。

三种触发(v1.0 规格):
  daily  每日首次开机   —— 当日未弹过 且 (有未完成任务 或 有需复习知识点)
  review 距复习<30min   —— 今日复习时段(review_time, 默认20:00)前30分钟起,
                           存在「需复习」知识点且当日未弹过; 开机晚于时段也补弹一次
  away   连续N天未打开  —— last_open_ts 距今 >= away_days(默认2) 且当日未弹过

公开 API:
  daily_first_open(now, tasks_state, cards, fired) -> {key,title,body} | None
  review_due(now, rem_cfg, cards, fired)           -> {key,title,body} | None
  away_return(now, last_open_ts, fired, away_days=2)-> {key,title,body} | None
  mark_fired(fired, now, key)                       -> dict   # 原地记账
  prune_fired(fired, today=None, keep_days=7)       -> dict   # 清理过期与脏键
  run_checks(learning_dir, now=None, ...)           -> list   # resident 每分钟调用

run_checks 契约(重要): resident 必须在更新 STATUS.last_open_ts 【之前】抓快照,
经 last_open_ts 参数传入, 否则回归提醒会被自己的新值永远压住。
"""
import json
import os
from datetime import datetime, date, time, timedelta

import settings as settings_mod


# ---------------- 纯函数: 三种判定 ----------------
def _date_key(now):
    """统一转成 'YYYY-MM-DD' 键"""
    if isinstance(now, datetime):
        return now.date().isoformat()
    if isinstance(now, date):
        return now.isoformat()
    return str(now)[:10]


def _need_review_concepts(cards):
    """提取「需复习」概念名, 保持原顺序"""
    return [c.get("concept", "") for c in (cards or [])
            if c.get("status") == "需复习" and c.get("concept")]


def daily_first_open(now, tasks_state, cards, fired):
    """每日首次开机: 有未完成任务或到期知识点才值得打扰"""
    today_key = _date_key(now)
    if "daily" in (fired.get(today_key) or []):
        return None
    days = (tasks_state or {}).get("days", {})
    bucket = days.get(today_key) or []
    undone = [t for t in bucket if not t.get("done")]
    need = _need_review_concepts(cards)
    if not undone and not need:
        return None                                       # 无事可说就不弹
    parts = []
    if bucket and not undone:
        parts.append("今日任务已全部完成")
    elif undone:
        first = (undone[0].get("text") or "").strip()
        parts.append("今日还有 %d 条任务未完成，先从「%s」开始"
                     % (len(undone), first))
    if need:
        names = "、".join("「%s」" % c for c in need[:2])
        tail = "" if len(need) <= 2 else " 等共 %d 个" % len(need)
        parts.append("知识点 %s%s 已到复习期" % (names, tail))
    return {"key": "daily", "title": "📌 今日待办",
            "body": "；".join(parts)}


def _parse_hhmm(text, fallback=None):
    """'HH:MM' -> time; 缺失/格式坏/数值越界一律回退默认 20:00。
    不做钳制: 把垃圾配置悄悄变成『错误但貌似合法』的时刻比回退更危险。"""
    fb = fallback or time(20, 0)
    try:
        hh, mm = str(text).split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return fb
        return time(hh, mm)
    except Exception:
        return fb


def review_due(now, rem_cfg, cards, fired):
    """复习临近: 复习时段前30分钟起, 有需复习知识点且当日未弹过。
    天粒度的间隔数据上, 「<30min」落地为「距用户设置的复习时段不足30分钟」。
    本函数自带 review_near 开关(它接收配置块, 就该由它认账)。"""
    cfg = rem_cfg or {}
    if not cfg.get("review_near", True):
        return None
    today_key = _date_key(now)
    if "review" in (fired.get(today_key) or []):
        return None
    need = _need_review_concepts(cards)
    if not need:
        return None
    shown_time = cfg.get("review_time", "20:00")
    start = datetime.combine(now.date(), _parse_hhmm(shown_time))
    if now < start - timedelta(minutes=30):               # 还没进 30 分钟窗口
        return None
    names = "、".join("「%s」" % c for c in need[:3])
    tail = "" if len(need) <= 3 else " 等共 %d 个" % len(need)
    return {"key": "review", "title": "🧠 复习提醒",
            "body": "距今日复习时段(%s)已不足 30 分钟：%s%s 该复习了——趁记忆还没溜走"
                    % (shown_time, names, tail)}


def away_return(now, last_open_ts, fired, away_days=2):
    """连续 N 天未打开的回归提醒。last_open_ts 解析失败一律静默(宁缺勿扰)。"""
    today_key = _date_key(now)
    if "away" in (fired.get(today_key) or []):
        return None
    if not last_open_ts:
        return None
    try:
        last = datetime.fromisoformat(str(last_open_ts))
    except ValueError:
        return None
    gap = (now.date() - last.date()).days
    try:
        threshold = int(away_days)
    except Exception:
        threshold = 2
    if gap < threshold:
        return None
    return {"key": "away", "title": "👋 好久不见",
            "body": "已经 %d 天没打开学习系统了。任务和复习都在原地等你，回来看看今日计划？" % gap}


# ---------------- fired 记账 ----------------
def mark_fired(fired, now, key):
    """当日命中记录: {'YYYY-MM-DD': ['daily', ...]}, 同键不重复"""
    lst = fired.setdefault(_date_key(now), [])
    if key not in lst:
        lst.append(key)
    return fired


def prune_fired(fired, today=None, keep_days=7):
    """清理: 早于保留窗口的日期键整体删除; 解析不了的脏键一并删除。原地修改并返回。"""
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    cutoff = today - timedelta(days=keep_days)
    for k in list(fired.keys()):
        try:
            d = date.fromisoformat(k)
        except ValueError:
            del fired[k]                                  # 脏键直接清
            continue
        if d < cutoff:
            del fired[k]
    return fired


# ---------------- 编排入口(resident 调用) ----------------
def _default_load_tasks(learning_dir):
    """读 tasks.json, 缺失/损坏返回空壳。utf-8-sig 兼容记事本手改(带BOM)的文件。"""
    p = os.path.join(learning_dir, "tasks.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _default_load_cards(learning_dir, today):
    """复习卡片来自 analyzer 四态状态机; 任何异常降级为空列表"""
    try:
        import analyzer
        return analyzer.get_review_cards(learning_dir, today=today)
    except Exception:
        return []


def _default_read_last_open(learning_dir):
    """从 STATUS.json 读上次打开时间(同样兼容 BOM)"""
    p = os.path.join(learning_dir, "STATUS.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f).get("last_open_ts")
    except Exception:
        return None


def run_checks(learning_dir, now=None, load_tasks_fn=None,
               load_cards_fn=None, last_open_ts=None):
    """resident 每分钟调用的编排入口:
    读设置 -> 组装数据(可注入) -> 依次跑三个判定(尊重开关) ->
    命中即记账并随 settings.json 落盘 -> 返回 [{key,title,body}, ...]
    无命中且无清理时不写盘, 保证空闲分钟零 IO。"""
    now = now or datetime.now()
    today = now.date()
    loaded = settings_mod.load_settings(learning_dir)
    cfg = loaded.setdefault("reminders", {})
    fired = cfg.get("fired") or {}
    before_keys = set(fired.keys())
    dirty = False
    msgs = []

    def _fire(result):
        nonlocal dirty
        if result:
            mark_fired(fired, now, result["key"])
            dirty = True
            msgs.append(result)

    load_tasks = load_tasks_fn or _default_load_tasks
    load_cards = load_cards_fn or _default_load_cards
    snapshot = last_open_ts                                # 调用方传入的开机前快照优先
    if snapshot is None:
        snapshot = _default_read_last_open(learning_dir)

    cards = load_cards(learning_dir, today)
    if cfg.get("daily_first_open", True):
        _fire(daily_first_open(now, load_tasks(learning_dir), cards, fired))
    if cfg.get("review_near", True):
        _fire(review_due(now, cfg, cards, fired))
    if cfg.get("away_nudge", True):
        _fire(away_return(now, snapshot, fired,
                          away_days=cfg.get("away_days", 2)))

    prune_fired(fired, today=today)                        # 顺手清过期, 不额外计费
    cfg["fired"] = fired
    if dirty or set(fired.keys()) != before_keys:
        settings_mod.save_settings(learning_dir, loaded)
    return msgs
