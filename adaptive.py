# -*- coding: utf-8 -*-
r"""adaptive.py —— 学习节奏自适应 (v1.2 · 纯标准库)

规格(v1.2):
  统计最近 7 天每日完成率(tasks.json history 的 rate 字段);
  近端连续 high_run(默认3) 天 rate >= high_rate(0.9) -> 次日任务量 ×(1+boost=+10%);
  近端连续 low_run(默认2) 天 rate <= low_rate(0.5)   -> 次日任务量 ×(1-reduce=-20%)
                                                    且插入休息建议(rest_hint);
  其余情况 ×1.0。两阈值区间不重叠, 不存在同时触发。
全部参数存 settings.json 的 adaptive 块(默认模板见 settings.DEFAULT_ADAPTIVE),
设置页可调; enabled=False 时恒为 off/×1.0。

设计: 判定与换算是纯函数(rates 与参数都由调用方注入), 单测用固定序列全分支覆盖;
与 tasks.json 的桥只有 recent_rates 一个薄函数。

公开 API:
  DEFAULT_ADAPTIVE 在 settings.py 定义(此处 re-export 语义引用)
  recent_rates(state, n=7)            -> [rate]      # history 升序取尾
  evaluate(rates, cfg=None)           -> {factor, state, reason, rest_hint}
                                         # state: boost|ease|flat|off
  apply_factor(predicted, factor)     -> int         # 四舍五入且下限保 1 条
"""
from settings import DEFAULT_ADAPTIVE

__all__ = ["recent_rates", "evaluate", "apply_factor"]


def recent_rates(state, n=7):
    """从 tasks.json 形状的数据取最近 n 天完成率(升序, 即最老在前最新在尾)"""
    hist = (state or {}).get("history", []) or []
    rates = []
    for h in hist:
        if not isinstance(h, dict):
            continue
        r = h.get("rate")
        if r is None:
            t = int(h.get("total", 0) or 0)
            r = (int(h.get("done", 0) or 0) / t) if t else 0.0
        try:
            rates.append(float(r))
        except (TypeError, ValueError):
            continue
    return rates[-max(0, int(n)):]


def _tail_run(rates, predicate):
    """从最新一天往回数的连续满足天数"""
    run = 0
    for r in reversed(rates):
        if predicate(r):
            run += 1
        else:
            break
    return run


def evaluate(rates, cfg=None):
    """核心判定纯函数。rates 升序(末位=今天); 缺数据给 flat 但带说明。"""
    cfg = dict(DEFAULT_ADAPTIVE if cfg is None else (cfg or {}))
    out = {"factor": 1.0, "state": "flat", "reason": "", "rest_hint": False}
    if not cfg.get("enabled", True):
        out["state"] = "off"
        out["reason"] = "自适应已关闭"
        return out
    rates = list(rates or [])
    if not rates:
        out["reason"] = "暂无收尾记录, 自适应待积累数据"
        return out

    high_rate = float(cfg.get("high_rate", 0.9))
    low_rate = float(cfg.get("low_rate", 0.5))
    boost = float(cfg.get("boost", 0.10))
    reduce = float(cfg.get("reduce", 0.20))

    # 先判低(保守优先): 万一参数被调成区间重叠, 减量优先于加量
    if _tail_run(rates, lambda r: r <= low_rate) >= max(1, int(cfg.get("low_run", 2))):
        out["state"] = "ease"
        out["factor"] = round(1.0 - reduce, 4)
        out["rest_hint"] = True
        out["reason"] = "连续 %d 天完成率≤%d%%, 次日减负 %d%% 并建议休整" % (
            max(1, int(cfg.get("low_run", 2))), round(low_rate * 100),
            round(reduce * 100))
        return out

    if _tail_run(rates, lambda r: r >= high_rate) >= max(1, int(cfg.get("high_run", 3))):
        out["state"] = "boost"
        out["factor"] = round(1.0 + boost, 4)
        out["rest_hint"] = False
        out["reason"] = "连续 %d 天完成率≥%d%%, 次日可加量 +%d%%" % (
            max(1, int(cfg.get("high_run", 3))), round(high_rate * 100),
            round(boost * 100))
    return out


def apply_factor(predicted, factor):
    """把系数应用到预测条数: 四舍五入, 结果至少 1 条(再累也不清零当日计划)。"""
    import math
    try:
        p = int(predicted)
        f = float(factor)
    except (TypeError, ValueError):
        return max(1, int(predicted)) if predicted else 1
    return max(1, int(math.floor(p * f + 0.5)))


# ---------------- Phase E-B/E-D: 多信号聚合与合成(护栏版) ----------------
CARRY_LOWER = 0.3                          # 顺延惩罚下限(低于不罚)
CARRY_UPPER = 0.5                          # 顺延惩罚上限(高于封顶)
CARRY_MAX_PENALTY = 0.20                   # 顺延惩罚封顶(与 E-B 一致, 不变)


def carry_over_rate(state, date=None, window=3):
    """窗口化顺延率(E-D): 最近 window 个「含任务」日期桶的 carried 占比均值。
    - 空桶/缺失日安全跳过, 不占窗口名额, 不产生 0 分母;
    - 无任何含任务桶 -> None(信号缺失, 不参与合成);
    - date 显式给出 -> 单日(legacy 单日行为); window=1 亦等效单日;
    - 确定性: 日期按 ISO 字典序(即时间序)取最近 window 个。
    目的(E-C): 抑制单日异常积压对整个信号的过冲。"""
    days = (state or {}).get("days", {}) or {}
    keys = [date] if date is not None else sorted(days.keys())
    ratios = []
    for k in keys:
        bucket = days.get(k)
        if not isinstance(bucket, list) or not bucket:
            continue                                  # 空桶/缺失日跳过
        carried = sum(1 for t in bucket if isinstance(t, dict) and t.get("carried"))
        ratios.append(carried / len(bucket))
        if date is not None:
            break
    ratios = ratios[-max(1, int(window)):]
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 4)


def _carry_penalty(carry_over):
    """连续线性顺延惩罚(E-D): <CARRY_LOWER → 0; [LOWER, UPPER] 线性增至
    CARRY_MAX_PENALTY; ≥UPPER → 封顶。无 0.4 阶跃, 单调不减:
    penalty(0.39) <= penalty(0.40) <= penalty(0.50)。"""
    if carry_over is None:
        return 0.0
    co = float(carry_over)
    if co <= CARRY_LOWER:
        return 0.0
    if co >= CARRY_UPPER:
        return CARRY_MAX_PENALTY
    return round((co - CARRY_LOWER) / (CARRY_UPPER - CARRY_LOWER)
                 * CARRY_MAX_PENALTY, 4)


def review_completion_ratio(learning_dir, today=None, days=7):
    """近 N 天复习完成比启发式: 近期已复习 / (当前到期 + 近期已复习), 有界 [0,1]。
    历史到期数不可精确重建(无逐日 due 台账), 用当前 due 近似; 无复习记录 -> None。"""
    try:
        import datetime as _dt
        import forgetting
        today = today or _dt.date.today()
        log = forgetting.load_knowledge(learning_dir).get("review_log", []) or []
        from_d = today - _dt.timedelta(days=days)
        recent = 0
        for e in log:
            ts = str(e.get("ts") or "")[:10]
            try:
                if _dt.date.fromisoformat(ts) >= from_d:
                    recent += 1
            except ValueError:
                continue
        if not recent:
            return None
        due = len(forgetting.due_cards(learning_dir, today=today))
        return round(min(1.0, recent / max(1, due + recent)), 4)
    except Exception:
        return None


def compose_factor(completion_factor, carry_over=None, fatigue=False,
                   review_ratio=None, cfg=None):
    """多信号加权合成 factor(E-B 护栏版, 纯函数确定性):

      - completion_factor: evaluate() 的完成率 factor(主信号);
      - carry_over 顺延率(0~1): 连续线性惩罚(E-D), [0.3,0.5] 线性至 0.20 封顶;
      - fatigue 疲劳: 强制 ×0.85;
      - review_ratio 复习完成比: <0.5 时 ×0.90(复习积压);
      - 缺失信号(None)一律跳过, 不参与;
      - 合成钳制 [0.6, 1.3]。

    设计护栏(E-A §9 + E-D): 权重独立封顶、缺数据退化为主信号、整体钳制,
    避免稀疏 history 上的过拟合; 负信号只减不增, 正向信号不补偿过载。"""
    cfg = cfg or {}
    f = float(completion_factor if completion_factor is not None else 1.0)
    f -= _carry_penalty(carry_over)
    if fatigue:
        f = round(f * 0.85, 4)
    if review_ratio is not None and review_ratio < 0.5:
        f = round(f * 0.90, 4)
    return round(max(0.6, min(1.3, f)), 4)
