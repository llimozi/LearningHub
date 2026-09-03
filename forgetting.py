# -*- coding: utf-8 -*-
r"""forgetting.py —— 遗忘曲线引擎 (v2.0 · 纯标准库 · FSRS 风格双参数调度)

定位: 知识点记忆档案的唯一写入者, 落盘 daily/knowledge.json。
台账(daily/analysis.json)回答「概念什么时候出现过」; 本模块回答「该不该复习了、
忘到什么程度、复习了几次」。analysis.json 保持只读——analyzer 会整文件重写,
把记忆字段塞进去会被抹掉(教训: 写入权唯一化)。

数据结构:
{
  "version": 2,
  "knowledge": {
    "<概念名>": {
      "first_seen": "YYYY-MM-DD",          # 最早出现日
      "source_date": "YYYY-MM-DD",         # 最近笔记日(点击跳转用)
      "last_review_ts": "ISO" | null,      # 最近一次标记复习的时刻
      "review_count": 0,                   # 复习次数
      "ease_factor": 2.5,                  # 掌握系数 1.3~3.0(v1 兼容字段, 双轨保留)
      "stability": 5.0,                    # v2: 记忆稳定性(天, FSRS 主调度参数)
      "difficulty": 0.3                    # v2: 概念难度 0.1~0.95(0~1 归一)
    }
  }
}

v2.0 升级(2026-09-03, Phase A1/A2):
  - 引入 FSRS 风格双参数: stability(S, 记忆强度/天) + difficulty(D, 固有难度)。
  - 遗忘曲线(双曲幂律, 用户确认): R(t) = (1 + t/S)^(-DECAY), DECAY 默认 0.09;
    旧 v1 记录(无 stability)完全回退 v1.1 的指数曲线与固定档位表, 零行为变化。
  - 间隔反解: interval = S * ((1/P_TARGET)^(1/DECAY) - 1), P_TARGET=0.90, 下限 1 天。
  - 复习驱动: 答对(q>=3) S*growth(q) 且 D*=0.95; 答错(q<3) S*=0.5 且 D+0.2;
    钳制 S∈[1,3650], D∈[0.1,0.95]; 首次复习自动初始化 S0/D0 并升级该记录。
  - v1.1 的 ease_factor 双轨保留(不删字段、不中断外部读取), 但调度只认 S/D。

公开 API:
  load_knowledge(dir) / save_knowledge(dir, data)
  sync_from_analysis(dir, analysis=None, today=None) -> (data, added)   # 只增不毁
  interval_days(record) -> int                    # 有 S 走 FSRS, 否则 v1 档位表
  mark_reviewed(dir, concept, now=None, quality=4) -> bool   # v2: 同时驱动 S/D
  retention_percent(record, today=None) -> int    # 有 S 走幂律, 否则 v1 指数
  due_cards(dir, today=None, top_n=None)   -> [{concept,status,overdue_days,...}]
  decay_rows(dir, today=None, top_n=20)    -> [{concept,retention,...}]
  calibrate_decay(learning_dir, data=None) -> float|None   # v2: 真实复习校准 DECAY
"""
import os
import json
import math
import datetime

KNOWLEDGE_NAME = "knowledge.json"
VERSION = 2
INTERVALS = (1, 2, 4, 7, 15, 30)              # v1 档位表(仅无 stability 记录回退用)
DEFAULT_EASE = 2.5
EASE_MIN = 1.3
EASE_MAX = 3.0
STABILITY_K = 1.6                             # v1 稳定度=有效间隔×此系数(仅回退用)

# ---- v2 FSRS 参数(Phase A) ----
P_TARGET = 0.90                               # 目标保持率(间隔反解锚点)
DECAY_DEFAULT = 0.09                          # 双曲幂律指数默认值(用户确认: 复现 S=5->11 示例)
DECAY_MIN, DECAY_MAX = 0.05, 0.50             # A3 校准网格范围(含默认 0.09)
S_MIN, S_MAX = 1.0, 3650.0                    # 稳定性钳制(天); S0 起步 0.5 是增长起点, 复习后进此区间
D_MIN, D_MAX = 0.10, 0.95                     # 难度钳制
D_DEFAULT = 0.30                              # 新记录难度初始值
S0_START = 0.5                                # 新记录 stability 起步值: 保证首复(growth 2.0)后 S=1,
                                              # 使首段间隔与 v1 档位平滑衔接(count=1 -> 2 天)
GROWTH = {3: 1.6, 4: 2.0, 5: 2.5}             # 答对 S 增长系数(q 越大拉越长)
_CAL_MIN_LOG = 30                             # A3 校准最少可用复习样本数


def _has_sd(record):
    """是否已是 v2 FSRS 记录(含可用 stability)。缺字段 -> 走 v1 回退。"""
    try:
        s = float(record.get("stability"))
    except (TypeError, ValueError):
        return False
    return s > 0


# ---------------- 存取 ----------------
def _path(learning_dir):
    return os.path.join(learning_dir, "daily", KNOWLEDGE_NAME)


def load_knowledge(learning_dir):
    try:
        with open(_path(learning_dir), encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("knowledge"), dict):
            return data
    except Exception:
        pass
    return {"version": VERSION, "knowledge": {}}


def save_knowledge(learning_dir, data):
    p = _path(learning_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ---------------- 同步 ----------------
def sync_from_analysis(learning_dir, analysis=None, today=None, normalize=False):
    """把台账里出现过的概念全部建档(只增不毁): 新概念记 first_seen/source_date,
    已有概念只推进 source_date——复习史与 ease 是本模块的私有资产, 同步无权碰。
    返回 (data, 本次新增数)。

    Phase D-B 可选归一化: normalize=True 时, 每篇笔记额外经
    normalize.normalize_concepts 产出高质量概念(tags/技术短语优先), 并入建档;
    归一化失败静默降级为旧行为; 不删除任何既有条目(旧噪音概念原样保留)。
    默认 normalize=False, 行为与旧版完全一致。"""
    today = today or datetime.date.today()
    if analysis is None:
        import analyzer
        analysis = analyzer.load_analysis(learning_dir)
    notes = analysis.get("notes", {}) if isinstance(analysis, dict) else {}
    appears = {}                                          # concept -> [dates]
    for ds in sorted(notes.keys()):
        rec = notes[ds]
        for c in (rec.get("concepts") or []) if isinstance(rec, dict) else []:
            c = str(c).strip()
            if c:
                appears.setdefault(c, [])
                if ds not in appears[c]:
                    appears[c].append(ds)
        # Phase D-B: 可选归一化, 追加高质量概念(不替代、不删旧)
        if normalize and isinstance(rec, dict):
            try:
                import normalize as _norm
                for n in _norm.normalize_concepts(rec):
                    key = str(n.get("concept") or "").strip()
                    if not key:
                        continue
                    appears.setdefault(key, [])
                    if ds not in appears[key]:
                        appears[key].append(ds)
            except Exception:
                pass                              # 归一化失败静默降级, 不影响既有同步
    data = load_knowledge(learning_dir)
    kn = data["knowledge"]
    added = 0
    changed = False
    for concept, dates in appears.items():
        rec = kn.get(concept)
        if rec is None:
            kn[concept] = {"first_seen": dates[0],
                           "source_date": dates[-1],
                           "last_review_ts": None,
                           "review_count": 0,
                           "ease_factor": DEFAULT_EASE,
                           "stability": S0_START,
                           "difficulty": D_DEFAULT}
            added += 1
            changed = True
        elif rec.get("source_date") != dates[-1]:
            rec["source_date"] = dates[-1]                # 出现过新笔记: 推进跳转锚点
            if not rec.get("first_seen"):
                rec["first_seen"] = dates[0]              # 旧档缺 first_seen 的补齐
            changed = True
    if changed:
        save_knowledge(learning_dir, data)                # 无变化零写盘(渲染路径高频调用)
    return data, added


# ---------------- 曲线核心 ----------------
def _v1_interval_days(record):
    """v1.1 原实现: 档位间隔 × (ease/2.5), 四舍五入, 下限 1 天(无 stability 记录回退用)"""
    count = int(record.get("review_count", 0) or 0)
    base = INTERVALS[min(max(count, 0), len(INTERVALS) - 1)]
    ease = float(record.get("ease_factor", DEFAULT_EASE) or DEFAULT_EASE)
    return max(1, int(round(base * ease / DEFAULT_EASE)))


def _fsrs_interval(record):
    """FSRS 间隔反解(双曲幂律): interval = S × ((1/P_TARGET)^(1/DECAY) − 1)。
    单调性: S↑ → interval↑(同 DECAY 下); DECAY↑ → interval↓。四舍五入, 下限 1 天。"""
    s = max(S_MIN, float(record.get("stability", S_MIN)))
    decay = float(record.get("decay", DECAY_DEFAULT) or DECAY_DEFAULT)
    ratio = (1.0 / P_TARGET) ** (1.0 / decay) - 1.0
    return max(1, int(round(s * ratio)))


def interval_days(record):
    """有效间隔: 已复习且有 stability(v2) 走 FSRS 反解;
    从未复习 或 无 stability(v1 回退) 走 v1.1 档位表——未复习概念不受升级影响。"""
    last = _as_date(record.get("last_review_ts"))
    if last is not None and _has_sd(record):
        return _fsrs_interval(record)
    return _v1_interval_days(record)


def _fsrs_retention(record, gap_days):
    """FSRS 保持率(双曲幂律): R = (1 + gap/S)^(-DECAY), gap 为距上次复习天数。"""
    s = max(S_MIN, float(record.get("stability", S_MIN)))
    decay = float(record.get("decay", DECAY_DEFAULT) or DECAY_DEFAULT)
    return (1.0 + max(0, gap_days) / s) ** (-decay)


def _init_sd(record):
    """旧记录(v1, 无 S/D)首次复习时初始化:
    S0 取该记录已积累的记忆强度——有复习史(v1 有效间隔天数)则按其反推,
    否则取新概念起步值 S0_START; D0 = 0.3。S0 为增长起点, 复习 growth 后才进钳制。
    返回 (S0, D0) 浮点。"""
    s0 = float(_v1_interval_days(record)) if int(record.get("review_count", 0) or 0) > 0 \
        else S0_START
    return round(s0, 2), D_DEFAULT


def _as_date(value, fallback=None):
    """'ISO日期时间'|'YYYY-MM-DD' -> date; 解析失败回退"""
    if not value:
        return fallback
    text = str(value)[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return fallback


def retention_percent(record, today=None):
    """记忆保持率 1~100:
    - 已复习且有 stability(v2): R = (1 + gap/S)^(-DECAY) 双曲幂律;
    - 从未复习(无 last_review_ts) 或 无 stability(v1 回退):
      R = exp(-gap / (首档间隔×1.6)) —— 未复习概念不受 v2 升级影响,
      语义与升级前完全一致(2026-09-03 用户裁决, recommender 集成测试锁定)。"""
    today = today or datetime.date.today()
    last = _as_date(record.get("last_review_ts"))
    if last is not None and _has_sd(record):
        gap = max(0, (today - last).days)
        return max(1, min(100, int(round(_fsrs_retention(record, gap) * 100))))
    eff = _v1_interval_days(record)
    anchor = last if last is not None else _as_date(record.get("first_seen"), today)
    if last is None:
        eff = INTERVALS[0]
    gap = max(0, (today - anchor).days)
    stability = max(1.0, eff * STABILITY_K)
    r = math.exp(-gap / stability)
    return max(1, min(100, int(round(r * 100))))


def mark_reviewed(learning_dir, concept, now=None, quality=4):
    """标记一次复习: review_count+1, last_review_ts=now,
    v2.0: quality 同时驱动 S/D ——
      首次复习(无 stability)先初始化 S0=v1 interval_days 反推值、D0=0.3 并升级记录;
      答对(q>=3): S *= growth(q) {3:1.6, 4:2.0, 5:2.5}, D *= 0.95;
      答错(q<3):  S *= 0.5, D = min(1.0, D+0.2);
      钳制 S∈[1,3650], D∈[0.1,0.95]。
    v1.1 兼容: ease 仍按 SM-2 公式双轨更新并钳制 1.3~3.0(不中断任何外部读取)。
    同时追加 review_log 事件流水(周报「复习次数」的真数据源, 封顶500条)。
    未建档概念返回 False 不写盘。"""
    data = load_knowledge(learning_dir)
    rec = data["knowledge"].get(concept)
    if rec is None:
        return False
    now = now or datetime.datetime.now()
    q = max(0, min(5, int(quality)))
    # ---- v2: S/D 更新(首次复习先初始化) ----
    if _has_sd(rec):
        s = float(rec.get("stability", S_MIN))
        d = float(rec.get("difficulty", D_DEFAULT) or D_DEFAULT)
    else:
        s0, d0 = _init_sd(rec)
        s, d = s0, d0
        rec["stability"] = s0
        rec["difficulty"] = d0
        data["version"] = VERSION                       # 记录升级: v1 -> v2
    if q >= 3:
        s *= GROWTH.get(q, GROWTH[4])
        d *= 0.95
    else:
        s *= 0.5
        d = min(1.0, d + 0.2)
    rec["stability"] = round(min(S_MAX, max(S_MIN, s)), 2)
    rec["difficulty"] = round(min(D_MAX, max(D_MIN, d)), 2)
    # ---- v1 兼容: ease 双轨更新 ----
    ease = float(rec.get("ease_factor", DEFAULT_EASE))
    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    rec["ease_factor"] = round(min(EASE_MAX, max(EASE_MIN, ease)), 2)
    rec["review_count"] = int(rec.get("review_count", 0)) + 1
    rec["last_review_ts"] = now.isoformat(timespec="seconds")
    rec.pop("snooze_until", None)      # v1.7: 真复习即解除软推迟
    log = data.setdefault("review_log", [])
    log.append({"ts": rec["last_review_ts"], "concept": concept, "quality": q})
    del log[:-500]
    save_knowledge(learning_dir, data)
    return True


# ---------------- v2.0 真实遗忘曲线校准 (Phase A3) ----------------
def _review_pairs(learning_dir):
    """从 review_log 构造 (concept, gap_days, outcome) 样本:
    同一概念相邻两次复习构成一个样本——
      gap   = 本次 ts - 上次 ts(天); outcome = 1(quality>=3 记住) / 0(忘了)。
    返回 [(concept, gap, outcome)]; 无配对复习则为空。"""
    data = load_knowledge(learning_dir)
    log = data.get("review_log") or []
    timeline = {}
    for e in log:
        if not isinstance(e, dict):
            continue
        c = str(e.get("concept") or "")
        ts = e.get("ts")
        if not c or not ts:
            continue
        timeline.setdefault(c, []).append((ts, int(e.get("quality", 0) or 0)))
    samples = []
    for c, events in timeline.items():
        events.sort(key=lambda x: x[0])
        for i in range(1, len(events)):
            try:
                t_prev = datetime.datetime.fromisoformat(events[i - 1][0])
                t_cur = datetime.datetime.fromisoformat(events[i][0])
            except ValueError:
                continue
            gap = max(1, int((t_cur - t_prev).total_seconds() // 86400))
            outcome = 1 if events[i][1] >= 3 else 0
            samples.append((c, gap, outcome))
    return samples


def calibrate_decay(learning_dir, data=None):
    """用真实复习记录拟合遗忘曲线指数 DECAY(双曲幂律 R=(1+gap/S)^(-DECAY))。
    方法(可复算): 网格搜索 DECAY ∈ [DECAY_MIN, DECAY_MAX] 步进 0.01,
    对每个候选值计算全体样本 log-loss = -Σ[y·ln(R)+(1-y)·ln(1-R)], 取最小者;
    R 逐样本计算: S 取该概念当前 stability(已升级)或 S0_START(未升级近似)。
    样本(配对复习)< _CAL_MIN_LOG 时静默返回默认——真实库当前仅 2 条, 走此分支。
    任何异常静默降级返回默认, 绝不影响主流程。"""
    try:
        if data is None:
            data = load_knowledge(learning_dir)
        log = data.get("review_log") or []
        if not isinstance(log, list):
            return DECAY_DEFAULT
        kn = data.get("knowledge") or {}
        samples = _review_pairs(learning_dir)
        if len(samples) < _CAL_MIN_LOG:
            return DECAY_DEFAULT                     # 数据不足: 静默默认, 不强行拟合
        best_d, best_loss = DECAY_DEFAULT, None
        for d_i in range(int(DECAY_MIN * 100), int(DECAY_MAX * 100) + 1):
            decay = d_i / 100.0
            loss = 0.0
            for concept, gap, y in samples:
                rec = kn.get(concept) or {}
                try:
                    s = float(rec.get("stability")) if rec.get("stability") else S0_START
                except (TypeError, ValueError):
                    s = S0_START
                s = max(0.1, s)
                r = min(0.999, max(0.001, (1.0 + gap / s) ** (-decay)))
                loss += -y * math.log(r) - (1 - y) * math.log(1 - r)
            if best_loss is None or loss < best_loss:
                best_d, best_loss = decay, loss
        return best_d
    except Exception:
        return DECAY_DEFAULT                        # 静默降级


# ---------------- 输出 ----------------
def _card(concept, record, today):
    """单条知识点 → 到期/衰减通用行(status 由 self_due 判定)"""
    last = _as_date(record.get("last_review_ts"))
    if last is None:
        anchor = _as_date(record.get("first_seen"), today)
        gap_since = max(0, (today - anchor).days)
    else:
        gap_since = max(0, (today - last).days)
    if not self_due(record, today):
        status = "未到期"
    elif (today - (_as_date(record.get("last_review_ts")) or
                   _as_date(record.get("first_seen"), today))).days \
            - (INTERVALS[0] if last is None else interval_days(record)) > 0:
        status = "已逾期"
    else:
        status = "今日待复习"
    return {
        "concept": concept,
        "status": status,
        "overdue_days": max(0, gap_since -
                            (INTERVALS[0] if last is None else interval_days(record))),
        "retention": retention_percent(record, today=today),
        "review_count": int(record.get("review_count", 0) or 0),
        "interval": interval_days(record),
        "gap_days": gap_since,
        "source_date": record.get("source_date") or record.get("first_seen"),
    }


def self_due(record, today):
    """是否已进入复习窗口: 复习过的看有效间隔, 未复习过的 D+1 起。
    v1.7: 支持 snooze_until 软推迟(CLI 减负模式)——未到推迟线一律不到期;
    真复习(mark_reviewed)即解除推迟。缺字段时行为与旧版完全一致。"""
    su = _as_date(record.get("snooze_until"))
    if su is not None and today < su:
        return False
    last = _as_date(record.get("last_review_ts"))
    if last is None:
        anchor = _as_date(record.get("first_seen"), today)
        return (today - anchor).days >= INTERVALS[0]
    return (today - last).days >= interval_days(record)


def due_cards(learning_dir, today=None, top_n=None):
    """今日待复习队列: 已进复习窗口的概念, 越危险(保持率越低)越靠前。
    status: 已逾期(超窗≥1天) / 今日待复习(恰好压线)。"""
    today = today or datetime.date.today()
    cards = []
    for concept, rec in load_knowledge(learning_dir)["knowledge"].items():
        if not self_due(rec, today):
            continue
        card = _card(concept, rec, today)
        card["status"] = "已逾期" if card["overdue_days"] > 0 else "今日待复习"
        cards.append(card)
    cards.sort(key=lambda c: (c["retention"], -c["review_count"], c["concept"]))
    if top_n:
        cards = cards[:top_n]
    return cards


def decay_rows(learning_dir, today=None, top_n=20):
    """记忆衰减卡片数据: 全部概念按保持率升序(最危险在前), 截前 top_n 行"""
    today = today or datetime.date.today()
    rows = [_card(c, r, today) for c, r in
            load_knowledge(learning_dir)["knowledge"].items()]
    rows.sort(key=lambda c: (c["retention"], c["concept"]))
    if top_n:
        rows = rows[:top_n]
    return rows
