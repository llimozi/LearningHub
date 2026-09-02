# -*- coding: utf-8 -*-
r"""forgetting.py —— 遗忘曲线引擎 (v1.1 · 纯标准库)

定位: 知识点记忆档案的唯一写入者, 落盘 daily/knowledge.json。
台账(daily/analysis.json)回答「概念什么时候出现过」; 本模块回答「该不该复习了、
忘到什么程度、复习了几次」。analysis.json 保持只读——analyzer 会整文件重写,
把记忆字段塞进去会被抹掉(教训: 写入权唯一化)。

数据结构:
{
  "version": 1,
  "knowledge": {
    "<概念名>": {
      "first_seen": "YYYY-MM-DD",          # 最早出现日
      "source_date": "YYYY-MM-DD",         # 最近笔记日(点击跳转用)
      "last_review_ts": "ISO" | null,      # 最近一次标记复习的时刻(v1.1 新增字段)
      "review_count": 0,                   # 复习次数(v1.1 新增字段)
      "ease_factor": 2.5                   # 掌握系数 1.3~3.0(SM-2 风格, v1.1 新增)
    }
  }
}

艾宾浩斯间隔表: 1 / 2 / 4 / 7 / 15 / 30 天, 按 review_count 取档;
实际间隔 = 档位 × (ease_factor/2.5), 下限 1 天——答得好拉长间隔, 答得差缩短。
记忆保持率: R = exp(-间隔天数 / 稳定度), 稳定度 = 实际间隔 × 1.6。

公开 API:
  load_knowledge(dir) / save_knowledge(dir, data)
  sync_from_analysis(dir, analysis=None, today=None) -> (data, added)   # 只增不毁
  interval_days(record) -> int
  mark_reviewed(dir, concept, now=None, quality=4) -> bool              # 打分 0~5
  retention_percent(record, today=None) -> int                          # 1~100
  due_cards(dir, today=None, top_n=None)   -> [{concept,status,overdue_days,...}]
  decay_rows(dir, today=None, top_n=20)    -> [{concept,retention,...}] # 记忆衰减卡
"""
import os
import json
import math
import datetime

KNOWLEDGE_NAME = "knowledge.json"
VERSION = 1
INTERVALS = (1, 2, 4, 7, 15, 30)
DEFAULT_EASE = 2.5
EASE_MIN = 1.3
EASE_MAX = 3.0
STABILITY_K = 1.6                                     # 稳定度=有效间隔×此系数


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
                           "ease_factor": DEFAULT_EASE}
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
def interval_days(record):
    """有效间隔 = 档位间隔 × (ease/2.5), 四舍五入, 下限 1 天"""
    count = int(record.get("review_count", 0) or 0)
    base = INTERVALS[min(max(count, 0), len(INTERVALS) - 1)]
    ease = float(record.get("ease_factor", DEFAULT_EASE) or DEFAULT_EASE)
    return max(1, int(round(base * ease / DEFAULT_EASE)))


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
    """记忆保持率 1~100: R = exp(-gap / (有效间隔×1.6));
    从未复习的概念用「距首次出现」的间隔, 稳定度按首档间隔算。"""
    today = today or datetime.date.today()
    eff = interval_days(record)
    anchor = _as_date(record.get("last_review_ts"))
    if anchor is None:
        anchor = _as_date(record.get("first_seen"), today)
        eff = INTERVALS[0]
    gap = max(0, (today - anchor).days)
    stability = max(1.0, eff * STABILITY_K)
    r = math.exp(-gap / stability)
    return max(1, min(100, int(round(r * 100))))


def mark_reviewed(learning_dir, concept, now=None, quality=4):
    """标记一次复习: review_count+1, last_review_ts=now,
    ease 按 SM-2 公式随质量调整并钳制在 1.3~3.0。
    同时追加 review_log 事件流水(周报「复习次数」的真数据源, 封顶500条)。
    未建档概念返回 False 不写盘。"""
    data = load_knowledge(learning_dir)
    rec = data["knowledge"].get(concept)
    if rec is None:
        return False
    now = now or datetime.datetime.now()
    q = max(0, min(5, int(quality)))
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
