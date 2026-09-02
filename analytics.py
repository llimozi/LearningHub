# -*- coding: utf-8 -*-
"""analytics.py —— v1.6 数据智能模块（纯 Python 标准库，零第三方依赖）

三个核心指标（设计文档见 README.md「数据智能」章节）：
  A. cognitive_load_index(state)          认知负荷指数 CLI(0~100)，预警 burnout
  B. knowledge_stability(learning_dir)    知识稳固度：按标签聚合遗忘曲线保持率
  C. focus_windows(state)                 最佳专注时段：done_at 完成时刻分布

诚实性约定（不伪造数据）：
  - C 依赖任务完成时间戳 done_at。v1.6 起 build_dashboard.toggle() 在勾选时写入；
    样本量 < MIN_FOCUS_SAMPLES 时返回 status="collecting"，绝不编造结论。
  - 所有函数接受 today 参数注入固定日期，保证单元测试确定性。

缓存：analytics_cache.json —— 源文件 mtime 变化 或 超过 CACHE_TTL 秒即重算，
否则直接复用上次结果（payload.cached=True），避免每次刷新重算历史。
"""
import datetime
import json
import logging
import os
from collections import OrderedDict

import planner
import forgetting

VERSION = "v1.0"
CACHE_NAME = "analytics_cache.json"
CACHE_TTL = 600                      # 缓存有效期(秒)
MIN_FOCUS_SAMPLES = 20               # 专注时段结论所需最少样本
PRIORITY_W = {1: 1.5, 2: 1.0, 3: 0.7}   # 优先级→负荷权重(P1 高优更耗神)

# 时段窗口: (标签, 起点小时, 终点小时)  —— 24 小时全覆盖无重叠
FOCUS_WINDOWS = (
    ("清晨 06-09", 6, 9),
    ("上午 09-12", 9, 12),
    ("午间 12-14", 12, 14),
    ("下午 14-17", 14, 17),
    ("傍晚 17-20", 17, 20),
    ("夜间 20-24", 20, 24),
    ("深夜 00-06", 0, 6),
)

JSON_READ_ERRORS = (OSError, UnicodeDecodeError, json.JSONDecodeError)
STAT_ERRORS = (TypeError, ValueError, ZeroDivisionError)
CACHE_ERRORS = JSON_READ_ERRORS + (KeyError, TypeError)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------- A. 认知负荷指数 ----------------
def _weighted(tasks, only_done=None):
    """桶内任务的优先级加权合计。only_done=True 只算已完成 / False 只算未完成 / None 全部。"""
    total = 0.0
    for t in tasks:
        if only_done is None or bool(t.get("done")) == only_done:
            total += PRIORITY_W.get(int(t.get("priority", 2)), 1.0)
    return total


def _capacity_avg7(state, today):
    """近 7 天(不含今天)日均加权消化量——衡量『这台机器一天能吃多少』。"""
    vals = []
    for i in range(1, 8):
        d = today - datetime.timedelta(days=i)
        bucket = state.get("days", {}).get(d.isoformat())
        if bucket:
            vals.append(_weighted(bucket, only_done=True))
    if not vals:
        return 0.0
    return sum(vals) / float(len(vals))


def _carry_streak(state, today):
    """截至昨天连续多少天『留了尾巴』(有桶且有未完成)。连排越久, 负荷压力越大。"""
    n = 0
    for i in range(1, 15):
        d = today - datetime.timedelta(days=i)
        bucket = state.get("days", {}).get(d.isoformat())
        if bucket and any(not t.get("done") for t in bucket):
            n += 1
        elif bucket:
            break                     # 遇到清干净的一天就停
    return n


def cognitive_load_index(state, today=None):
    """CLI = clamp(0..100, (55*ratio + 25*backlog + 20*streak) * fatigue_mult)
      ratio   : 今日加权负荷 ÷ (近7天日均加权消化×2) —— 达到容量2倍记满分
      backlog : 今日未完成任务占比
      streak  : 连续欠账天数压力 = min(连排天数,7)/7
      fatigue_mult : planner 疲劳检测激活时 ×1.25
    返回 {index, zone, advice, factors{...}} —— factors 全透明可解释。"""
    today = today or datetime.date.today()
    bucket = state.get("days", {}).get(today.isoformat(), [])
    fat = planner.detect_fatigue(state)

    if not bucket and not state.get("history"):
        return {"index": 0, "zone": "轻松",
                "advice": "今天还没有安排任务——去 daily 笔记里写一条，或点「📝 写笔记」开始",
                "factors": {}}

    capacity = max(_capacity_avg7(state, today), 0.8)
    w_today = _weighted(bucket)
    ratio_norm = _clamp(w_today / (capacity * 2.0), 0.0, 1.0)
    backlog = (sum(1 for t in bucket if not t.get("done")) / float(len(bucket))) if bucket else 0.0
    streak_days = _carry_streak(state, today)
    streak_norm = min(streak_days, 7) / 7.0
    mult = 1.25 if fat.get("active") else 1.0

    base = 55.0 * ratio_norm + 25.0 * backlog + 20.0 * streak_norm
    index = int(_clamp(round(base * mult), 0, 100))

    if index <= 35:
        zone, advice = "轻松", "节奏舒适——适合安排一个略有挑战的新知识点"
    elif index <= 60:
        zone, advice = "适中", "保持当前节奏，优先清掉顺延下来的旧任务"
    elif index <= 80:
        zone, advice = "偏重", "今天别再加新内容了——右键把 P3 低优任务往后放一放"
    else:
        zone, advice = "过载", "触发保护模式——只保留 P1 高优，其余整批顺延；今晚早点收尾"

    return {"index": index, "zone": zone, "advice": advice,
            "factors": {"load_today": round(w_today, 2), "capacity_avg7": round(capacity, 2),
                        "ratio_norm": round(ratio_norm, 3), "backlog_ratio": round(backlog, 3),
                        "carry_streak_days": streak_days,
                        "fatigue_active": bool(fat.get("active"))}}


# ---------------- B. 知识稳固度(按标签聚合) ----------------
QW = {5: 1.0, 4: 0.9, 3: 0.7, 2: 0.5, 1: 0.3, 0: 0.1}   # 复习质量->打折系数(v1.8 A2)


def _quality_adjust(raw, hist, today):
    """v1.8 A2: 按复习质量加权保持率。
    为什么用乘法而非替换: 保持率是记忆本身的状态, 质量只是『折扣系数』;
    为什么加时间衰减(半衰期30天): 三个月前一次敷衍的复习不该与昨天的高分同权;
    为什么从未复习的概念原样返回: 没有质量信号就绝不编造。"""
    if not hist:
        return raw, None, False
    num = den = 0.0
    last_q = None
    for ev in hist:
        try:
            q = max(0, min(5, int(ev.get("quality", 3))))
        except STAT_ERRORS:
            q = 3
        last_q = q
        d = forgetting._as_date(ev.get("ts"), today)
        gap = max(0, (today - d).days) if d else 0
        w = 0.5 ** (gap / 30.0)
        num += w * QW.get(q, 0.7)
        den += w
    qw = num / den if den > 0 else 1.0
    eff = max(1, int(round(raw * qw)))
    flagged = (raw - eff) >= round(raw * 0.15)      # 加权后缩水>=15% -> 提示“复习了但质量不高”
    return eff, last_q, flagged


def knowledge_stability(learning_dir, today=None, weight_quality=True):
    """把遗忘曲线的概念级保持率按笔记标签聚合：
       avg_retention = 该标签下全部概念 R=exp(-gap/稳定期) 的均值。
    数据源: daily/knowledge.json(forgitting) × daily/analysis.json(analyzer 的概念↔日期↔标签)。
    无标签概念归入「未分类」。输出按平均保持率升序(最薄弱的排最前)。"""
    today = today or datetime.date.today()
    data_raw = forgetting.load_knowledge(learning_dir)
    knowledge = data_raw.get("knowledge", {})
    if not knowledge:
        return {"status": "empty", "overall": None, "rows": [], "dist": {},
                "weakest_tag": None,
                "advice": "还没有知识点档案——保存一篇笔记，这里就会长出你的记忆花园"}

    # 概念 → 标签(取该概念出现过的所有笔记日期的 tags 并集)
    notes = _load_analysis_notes(learning_dir)
    concept_tags = {}
    for ds in sorted(notes.keys()):
        for c in notes[ds].get("concepts", []):
            lst = concept_tags.setdefault(c, [])
            for tg in notes[ds].get("tags", []):
                if tg and tg not in lst:
                    lst.append(tg)

    review_hist = {}
    for ev in data_raw.get("review_log", []) or []:
        c = ev.get("concept")
        if c:
            review_hist.setdefault(c, []).append(ev)

    agg = OrderedDict()                # tag -> [(concept, eff, raw, last_q, flagged)]
    for concept, rec in knowledge.items():
        raw = forgetting.retention_percent(rec, today=today)
        if weight_quality and review_hist.get(concept):
            eff, last_q, flagged = _quality_adjust(raw, review_hist[concept], today)
        else:
            eff, last_q, flagged = raw, None, False   # 未复习: 无质量信号, 原样呈现
        tags = concept_tags.get(concept) or ["未分类"]
        for tg in tags:
            agg.setdefault(tg, []).append((concept, eff, raw, last_q, flagged))

    rows = []
    red = yellow = green = 0
    for tg, pairs in agg.items():
        rs = [eff for _, eff, _, _, _ in pairs]          # eff=质量加权后的保持率
        avg = int(round(sum(rs) / float(len(rs))))
        if avg < 40:
            red += 1
        elif avg < 70:
            yellow += 1
        else:
            green += 1
        wc, wr, wq = min(((c, eff, q) for c, eff, _, q, _ in pairs), key=lambda x: x[1])
        rows.append({"tag": tg, "avg_retention": avg, "n_concepts": len(rs),
                     "weakest_concept": wc, "weakest_retention": wr,
                     "concepts": [{"name": c, "retention": eff, "retention_raw": raw,
                                   "quality": q, "flagged": fl}
                                  for c, eff, raw, q, fl
                                  in sorted(pairs, key=lambda p: p[1])]})

    rows.sort(key=lambda x: (x["avg_retention"], -x["n_concepts"]))
    all_eff = [c["retention"] for row in rows for c in row["concepts"]]   # v1.8: overall 同步用加权值
    overall = int(round(sum(all_eff) / float(len(all_eff)))) if all_eff else 0
    weakest_tag = rows[0]["tag"] if rows else None
    return {"status": "ready", "overall": overall, "rows": rows[:10],
            "dist": {"red_lt40": red, "yellow_40_69": yellow, "green_ge70": green},
            "weakest_tag": weakest_tag,
            "advice": ("最薄弱领域是 #" + str(weakest_tag) + " —— 复习中心优先刷它的卡片；"
                       "稳固标签(绿)可降低复习频率，把时间让给红黄区") if weakest_tag else ""}


def _load_analysis_notes(learning_dir):
    """读 analyzer 的 analysis.json(结构化失败一律回退空表, 不抛错)。"""
    p = os.path.join(learning_dir, "daily", "analysis.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data.get("notes", {}) if isinstance(data, dict) else {}
    except JSON_READ_ERRORS:
        return {}


# ---------------- C. 最佳专注时段 ----------------
def focus_windows(state, min_samples=None):
    """统计全部历史勾选的 done_at 时刻分布(v1.6 起 toggle 自动记录)。
    样本不足时诚实返回 status="collecting"——只报进度, 不下结论。"""
    need = MIN_FOCUS_SAMPLES if min_samples is None else int(min_samples)
    hours = []
    for bucket in (state.get("days", {}) or {}).values():
        for t in bucket or []:
            if t.get("done") and t.get("done_at"):
                try:
                    hours.append(int(str(t["done_at"])[11:13]))
                except (ValueError, IndexError):
                    pass
    samples = len(hours)
    if samples < need:
        return {"status": "collecting", "samples": samples, "need": need,
                "buckets": [],
                "hint": "每次勾选完成都会自动记录时刻——正常学习积累即可，无需额外操作"}
    counts = OrderedDict()
    for label, lo, hi in FOCUS_WINDOWS:
        counts[label] = 0
    for h in hours:
        for label, lo, hi in FOCUS_WINDOWS:
            if lo <= h < hi:
                counts[label] += 1
                break
    total = float(samples)
    buckets = [{"label": k, "count": v,
                "share": int(round(v * 100 / total))} for k, v in counts.items()]
    best_label = max(buckets, key=lambda b: b["count"])["label"]
    best = next(b for b in buckets if b["label"] == best_label)
    return {"status": "ready", "samples": samples, "need": need,
            "buckets": buckets, "best_window": best_label,
            "best_share": best["share"],
            "advice": ("你常在「" + best_label + "」完成任务(占" + str(best["share"])
                       + "%)——难度高的新知识优先排进这个时段，机械性事务放在低谷期")}


# ---------------- 缓存与总入口 ----------------
def _src_mtimes(learning_dir):
    out = {}
    for rel in ("tasks.json", os.path.join("daily", forgetting.KNOWLEDGE_NAME),
                os.path.join("daily", "analysis.json")):
        p = os.path.join(learning_dir, rel)
        try:
            out[rel] = os.stat(p).st_mtime
        except OSError:
            out[rel] = 0
    return out


def _duration_summary(state):
    """v1.8 A3 微指标: 近7天预估总耗时 vs 实际耗时。
    actual 样本<5 次时诚实返回 collecting——只有几次采样做不出可靠偏差结论。"""
    today = datetime.date.today()
    est = act = 0
    n_act = 0
    for i in range(0, 8):
        d = today - datetime.timedelta(days=i)
        for t in state.get("days", {}).get(d.isoformat(), []) or []:
            if i == 0 or t.get("done"):
                est += int(t.get("est_minutes") or 0)
            if t.get("done") and t.get("actual_minutes"):
                act += int(t["actual_minutes"])
                n_act += 1
    return {"status": "ready" if n_act >= 5 else "collecting",
            "est_week_min": est, "actual_week_min": act,
            "actual_samples": n_act,
            "hint": "在 daily 任务里写「≤45min」即可自动识别耗时; 补录浮层可顺手填实际用时"}


def _compute(learning_dir, today):
    try:
        with open(os.path.join(learning_dir, "tasks.json"), encoding="utf-8-sig") as f:
            state = json.load(f)
    except JSON_READ_ERRORS:
        state = {"days": {}, "history": []}
    return {
        "version": VERSION,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "cli": cognitive_load_index(state, today=today),
        "stability": knowledge_stability(learning_dir, today=today),
        "focus": focus_windows(state),
        "duration": _duration_summary(state),
    }


def get_analytics(learning_dir=None, today=None, force=False):
    """总入口: 先查缓存(mtime 未变且未超 TTL 直接复用), 否则重算并落盘。
    today 注入固定日期时建议 force=True 以免读到旧缓存。"""
    ld = learning_dir or os.path.dirname(os.path.abspath(__file__))
    cpath = os.path.join(ld, CACHE_NAME)
    mtimes = _src_mtimes(ld)
    if not force:
        try:
            with open(cpath, encoding="utf-8-sig") as f:
                cache = json.load(f)
            age = (datetime.datetime.now() - datetime.datetime.fromisoformat(cache["built_ts"])).total_seconds()
            if age < CACHE_TTL and cache.get("mtimes") == mtimes:
                payload = dict(cache["payload"])
                payload["cached"] = True
                return payload
        except CACHE_ERRORS as e:
            logging.error("Analytics cache ignored in get_analytics: %s", e,
                          exc_info=True)
    payload = _compute(ld, today)
    payload["cached"] = False
    try:
        with open(cpath, "w", encoding="utf-8-sig") as f:
            json.dump({"built_ts": datetime.datetime.now().isoformat(timespec="seconds"),
                       "mtimes": mtimes, "payload": payload}, f, ensure_ascii=False)
    except OSError:
        pass                          # 写缓存失败不影响主流程
    return payload


def invalidate_cache(learning_dir=None):
    """手动失效(如刚批量导入了历史数据)。文件不存在则静默跳过。"""
    ld = learning_dir or os.path.dirname(os.path.abspath(__file__))
    try:
        os.remove(os.path.join(ld, CACHE_NAME))
    except OSError:
        pass
# -*- coding: utf-8 -*-
"""v1.8 阶段二扩展: B1 预测性排期 + B2 叙事化周报 (由补丁器追加到 analytics.py 末尾)"""


# ---------------- v1.8 B1: 预测性排期 ----------------
def suggest_slot(state, priority=2, tag=None, est_minutes=None,
                 today=None, learning_dir=None):
    """三源综合回答『下一个任务排哪里』。
    源1 focus : focus_windows ready 才参与(collecting 时诚实跳过);
    源2 load  : 今日+未来2天负荷 = SUM(est_minutes 或默认30) x PRIORITY_W;
                所有任务都无 est_minutes 时降级为按任务计数排序;
    源3 stab  : tag 与 weakest_tag 命中 -> weakness_alert 提醒先复习。
    confidence: 三源齐全=high / 两源=mid / 仅负荷=low。
    为什么复用 PRIORITY_W 而非另设权重: 与 CLI 同一杆秤, 建议之间才不打架。"""
    today = today or datetime.date.today()
    sources = []
    reasons = []

    fw = focus_windows(state)
    suggested_window = None
    if fw.get("status") == "ready":
        suggested_window = fw.get("best_window")
        sources.append("focus")
        reasons.append("你的最佳专注窗口(" + str(suggested_window) + ")")

    pw_default = PRIORITY_W.get(int(priority or 2), 1.0)
    new_load = (est_minutes or 30) * pw_default
    day_rows = []
    any_est = False
    for i in range(0, 3):
        d = today + datetime.timedelta(days=i)
        bucket = state.get("days", {}).get(d.isoformat(), []) or []
        load, count = 0.0, 0
        for t in bucket:
            count += 1
            w = PRIORITY_W.get(int(t.get("priority", 2)), 1.0)
            em = t.get("est_minutes")
            if em:
                any_est = True
                load += int(em) * w
            else:
                load += 30 * w
        day_rows.append({"day": d.isoformat(),
                         "label": "今天" if i == 0 else ("明天" if i == 1 else "后天"),
                         "load": round(load), "count": count})
    if not any_est:
        for r0 in day_rows:
            r0["load"] = r0["count"]          # 降级: 全部缺耗时数据 -> 按任务计数
    best = min(day_rows, key=lambda x: (x["load"], x["count"]))
    suggested_day = best["day"]
    sources.append("load")
    unit = "min负荷" if any_est else "项任务"
    reasons.append(best["label"] + "负荷最低(~" + str(best["load"]) + " " + unit + ")")

    weakness_alert = False
    if tag and learning_dir:
        ks = knowledge_stability(learning_dir, today=today)
        if ks.get("status") == "ready":
            sources.append("stability")
            if ks.get("weakest_tag") == tag:
                weakness_alert = True
                reasons.insert(0, "#" + str(tag) + " 当前最薄弱, 建议优先安排")

    n = len(sources)
    confidence = {3: "high", 2: "mid"}.get(n, "low")
    return {"suggested_day": suggested_day,
            "suggested_day_label": best["label"],
            "suggested_window": suggested_window,
            "reason": " + ".join(reasons) if reasons else "按默认节奏安排",
            "confidence": confidence,
            "weakness_alert": weakness_alert,
            "sources": sources,
            "day_loads": day_rows}


# ---------------- v1.8 B2: 叙事化周报 ----------------
def generate_weekly_narrative(learning_dir=None, week="current", today=None):
    """把本周数字翻译成一段人话。
    为什么不做 CLI 环比: 系统没有历史 CLI 快照, 编造对比就是撒谎;
    完成率环比有 history.rate 可查, 是唯一有据的对比维度(留待后续)。"""
    ld = learning_dir or os.path.dirname(os.path.abspath(__file__))
    today = today or datetime.date.today()
    payload = get_analytics(ld)                       # 走缓存, 不重复计算
    cli = payload.get("cli", {})
    stb = payload.get("stability", {})
    foc = payload.get("focus", {})
    dur = payload.get("duration", {})

    try:
        with open(os.path.join(ld, "tasks.json"), encoding="utf-8-sig") as f:
            state = json.load(f)
    except JSON_READ_ERRORS:
        state = {"days": {}, "history": []}

    if week == "last":
        end = today - datetime.timedelta(days=today.weekday())       # 本周一
        start = end - datetime.timedelta(days=7)
    else:
        start = today - datetime.timedelta(days=today.weekday())     # 周一锚定
        end = today

    total = done = 0
    full_days = 0
    est_sum = act_sum = act_n = 0
    cur = start
    while cur <= end and cur <= today:
        bucket = state.get("days", {}).get(cur.isoformat(), []) or []
        if bucket:
            dn = sum(1 for t in bucket if t.get("done"))
            done += dn
            total += len(bucket)
            if dn == len(bucket):
                full_days += 1
            for t in bucket:
                if t.get("done"):
                    est_sum += int(t.get("est_minutes") or 0)
                    if t.get("actual_minutes"):
                        act_sum += int(t["actual_minutes"])
                        act_n += 1
        cur += datetime.timedelta(days=1)

    hist = [h for h in state.get("history", [])
            if start.isoformat() <= str(h.get("date", ""))[:10] <= end.isoformat()]
    if not total and not hist:
        return {"status": "collecting",
                "message": "数据积累中, 下周解锁完整叙事报告",
                "period": start.isoformat() + " ~ " + end.isoformat()}

    completion_rate = (int(round(done * 100 / float(total))) if total else
                       (int(round(sum(h.get("rate", 0) for h in hist) / float(len(hist))))
                        if hist else 0))

    review_log = forgetting.load_knowledge(ld).get("review_log", []) or []
    wk_reviews = [e for e in review_log
                  if start.isoformat() <= str(e.get("ts", ""))[:10] <= end.isoformat()]
    avg_q = (int(round(sum(e.get("quality", 3) for e in wk_reviews) / float(len(wk_reviews))))
             if wk_reviews else None)

    highlights = []
    if full_days:
        highlights.append("有 " + str(full_days) + " 天清掉了当天全部任务")
    streak = None
    try:
        with open(os.path.join(ld, "STATUS.json"), encoding="utf-8-sig") as f:
            streak = json.load(f).get("streak")
    except JSON_READ_ERRORS:
        pass
    if isinstance(streak, int) and streak >= 3:
        highlights.append("连续打卡 " + str(streak) + " 天")
    if avg_q is not None and avg_q >= 4:
        highlights.append("复习质量保持高水准(均分 " + str(avg_q) + "/5)")

    concerns = []
    fat = planner.detect_fatigue(state)
    if fat.get("active"):
        concerns.append("疲劳模式进行中(" + str(fat.get("reason", ""))[:40] + ")")
    cs = _carry_streak(state, today)
    if cs >= 3:
        concerns.append("已连续 " + str(cs) + " 天留欠账, 注意连排压力")
    if avg_q is not None and avg_q < 3:
        concerns.append("复习质量偏低(均分 " + str(avg_q) + "/5), 低质量复习留存有限")
    if act_n and dur.get("est_week_min", 0) > act_sum * 1.5:
        concerns.append("预估耗时明显高于实际投入, 排量可能偏乐观")

    bits = []
    if stb.get("weakest_tag"):
        bits.append("#" + str(stb["weakest_tag"]) + " 保持率最低, 优先排它的复习卡")
    try:
        tm = planner.predict_tomorrow(state)
        bits.append("明日建议约 " + str(tm.get("predicted", "?")) + " 条任务")
    except STAT_ERRORS:
        pass
    next_week_suggestion = "; ".join(bits) if bits else "保持当前节奏"

    headline = ("本周认知负荷 " + str(cli.get("index")) + "(" + str(cli.get("zone")) + ")"
                if cli.get("index") is not None else "本周数据积累中")
    focus_best = None
    if foc.get("status") == "ready":
        focus_best = str(foc.get("best_window")) + "(占完成量 " + str(foc.get("best_share")) + "%)"

    return {"status": "ready",
            "period": start.isoformat() + " ~ " + end.isoformat(),
            "headline": headline,
            "highlights": highlights[:3],
            "concerns": concerns[:2],
            "focus_best": focus_best,
            "next_week_suggestion": next_week_suggestion,
            "stats": {"completion_rate": completion_rate, "total_tasks": total,
                      "done_tasks": done, "full_days": full_days,
                      "review_count": len(wk_reviews), "avg_quality": avg_q,
                      "est_week_min": dur.get("est_week_min"),
                      "actual_week_min": dur.get("actual_week_min")},
            "cli_index": cli.get("index")}
