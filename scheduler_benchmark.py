# -*- coding: utf-8 -*-
r"""scheduler_benchmark.py —— 新旧调度算法可量化 Benchmark (Phase A4 · 纯标准库)

对比对象:
  旧 v1.1: 固定档位表(1,2,4,7,15,30) × ease/2.5, 指数保持率 R=exp(-gap/(间隔×1.6))
  新 v2.0: FSRS 风格双参数(S/D), 双曲幂律 R=(1+gap/S)^(-DECAY), P_TARGET=0.90

模拟协议 v2(确定性, 可复算, 按真实时间推进):
  - 固定随机种子; 100 个概念各自独立时间线, 模拟 365 天
  - 概念真实记忆: 双曲幂律 R_real(gap) = (1+gap/S_real)^(-DECAY_real),
    参数对两调度器隐藏(公平)——S_real 由「概念难度」决定, 难度高->S_real 小->忘得快
  - 调度器只做两件事: 到期日(next_due)与复习后更新(observe)
  - 到到期日: 以 R_real(gap) 概率记住(q=4) / 忘记(q=1); 调度器 observe(q)
  - 未到期绝不复习(尊重调度器), 因此总复习次数反映调度间隔效率
  - 额外统计: 每天结束时概念的记忆状态(记住概率), 计算全年平均「记忆健康度」

指标(诚实对比): 总复习次数 / 平均到期保持率(真实 R_real at 到期) /
  间隔中位数与 P90 / 全年概念平均真实保持率(健康度)。

用法: python scheduler_benchmark.py
产物: tests_output/scheduler_benchmark.md
诚实声明: 数字是多少就是多少; 不占优的指标如实呈现并给原因。
"""
import os
import math
import random
import datetime

import forgetting

N_CONCEPTS = 100
SIM_DAYS = 365
SEED = 20260903
P_TARGET = forgetting.P_TARGET

# 真实概念记忆分布(用户侧不可观测, 公平基准)
REAL_DECAY = 0.20                     # 真实遗忘指数(用户记忆的固有衰减)
REAL_S_LOGMEAN = 2.0                  # log(S_real) 均值: S_real 几何均值 ~ e^2 ≈ 7.4 天
REAL_S_LOGSIGMA = 0.6                 # 概念间差异


def _real_retention(gap, s_real):
    """真实记忆: 双曲幂律。gap 为该概念自上次复习以来的真实天数。"""
    return (1.0 + gap / s_real) ** (-REAL_DECAY)


class _V1Track:
    """旧调度: 固定档位表 × ease/2.5 + SM-2 ease 更新。"""
    def __init__(self):
        self.count = 0
        self.ease = 2.5
        self.due_day = 1                # 首次复习定在第 1 天(学习后次日)

    def next_due(self):
        return self.due_day

    def observe(self, q, today):
        self.count += 1
        e = self.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        self.ease = max(1.3, min(3.0, e))
        iv = forgetting.INTERVALS[min(self.count, len(forgetting.INTERVALS) - 1)]
        self.due_day = today + max(1, int(round(iv * self.ease / forgetting.DEFAULT_EASE)))


class _V2Track:
    """新调度: FSRS S/D(与 forgetting v2 规则一致, 独立实现避免文件耦合)。"""
    def __init__(self):
        self.s = 0.5
        self.d = 0.3
        self.due_day = 1

    def next_due(self):
        return self.due_day

    def observe(self, q, today):
        if q >= 3:
            self.s *= forgetting.GROWTH.get(q, forgetting.GROWTH[4])
            self.d *= 0.95
        else:
            self.s *= 0.5
            self.d = min(1.0, self.d + 0.2)
        self.s = max(1.0, min(3650.0, self.s))
        self.d = max(0.10, min(0.95, self.d))
        ratio = (1.0 / P_TARGET) ** (1.0 / forgetting.DECAY_DEFAULT) - 1.0
        self.due_day = today + max(1, int(round(self.s * ratio)))


def _simulate(factory):
    """按真实时间推进模拟 365 天。返回指标 dict。"""
    rng = random.Random(SEED)
    concepts = []
    for i in range(N_CONCEPTS):
        s_real = math.exp(rng.gauss(REAL_S_LOGMEAN, REAL_S_LOGSIGMA))
        concepts.append({"s_real": s_real,
                         "track": factory(),
                         "last_review": 0})       # 第 0 天=学习日
    total_reviews = 0
    real_at_review = []            # 每次到期复习时的真实 R
    intervals = []                 # 实际间隔(gap = today - last_review)
    reached0 = 0                   # 全年保持率跌破 0.5 的概念数(健康度反向指标)
    # 全年健康度: 每 7 天采样所有概念的真实 R
    health_samples = []
    for day in range(1, SIM_DAYS + 1):
        for c in concepts:
            tr = c["track"]
            if day < tr.next_due():
                continue
            gap = day - c["last_review"]
            r_real = _real_retention(gap, c["s_real"])
            remembered = rng.random() < r_real
            q = 4 if remembered else 1
            tr.observe(q, day)
            c["last_review"] = day
            total_reviews += 1
            intervals.append(gap)
            real_at_review.append(r_real)
        if day % 7 == 0:
            hs = 0.0
            for c in concepts:
                gap = day - c["last_review"]
                hs += _real_retention(gap, c["s_real"])
            health_samples.append(hs / N_CONCEPTS)
    return {
        "total_reviews": total_reviews,
        "avg_reviews_per_concept": total_reviews / N_CONCEPTS,
        "avg_real_at_review": (sum(real_at_review) / len(real_at_review)
                               if real_at_review else 0.0),
        "p50_interval": _percentile(intervals, 50) if intervals else 0,
        "p90_interval": _percentile(intervals, 90) if intervals else 0,
        "max_interval": max(intervals) if intervals else 0,
        "health_mean": (sum(health_samples) / len(health_samples)
                        if health_samples else 0.0),
    }


def _percentile(xs, p):
    if not xs:
        return 0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(len(s) * p / 100.0))))
    return s[k]


def _fmt(v):
    return ("%.2f" % v) if isinstance(v, float) else str(v)


def _markdown(old, new):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    L = []
    L.append("# 调度算法 Benchmark · 旧 SM-2 简化 vs 新 FSRS 风格")
    L.append("")
    L.append("> 生成: %s ｜ %d 概念独立时间线 × %d 天(种子 %d, 确定性可复算) ｜ P_TARGET=%.2f"
             % (now, N_CONCEPTS, SIM_DAYS, SEED, P_TARGET))
    L.append("> 真实记忆: 双曲幂律 DECAY=%.2f, S_real 几何均值≈%.0f 天(对两调度器隐藏, 公平)"
             % (REAL_DECAY, math.exp(REAL_S_LOGMEAN)))
    L.append("")
    L.append("## 对比表")
    L.append("")
    L.append("| 指标 | 旧 v1.1(SM-2 档位+ease) | 新 v2.0(FSRS S/D) | 读数方向 |")
    L.append("|---|---|---|---|")
    rows = [
        ("总复习次数(365天×100概念)", old["total_reviews"], new["total_reviews"], "↓ 少=省力"),
        ("每概念年均复习次数", old["avg_reviews_per_concept"], new["avg_reviews_per_concept"], "↓ 少=省力"),
        ("到期时真实保持率", old["avg_real_at_review"], new["avg_real_at_review"], "↑ 高=记忆更稳"),
        ("间隔中位数(天)", old["p50_interval"], new["p50_interval"], "↑ 高=复习间隔合理拉长"),
        ("间隔 P90(天)", old["p90_interval"], new["p90_interval"], "↑ 高=稳定概念被稀疏化"),
        ("最长间隔(天)", old["max_interval"], new["max_interval"], "信息参考"),
        ("全年平均真实保持率(健康度)", old["health_mean"], new["health_mean"], "↑ 高=整体记忆更牢"),
    ]
    for name, o, n, note in rows:
        L.append("| %s | **%s** | **%s** | %s |" % (name, _fmt(o), _fmt(n), note))
    L.append("")
    L.append("## 诚实分析(数字是多少就是多少)")
    dr = new["total_reviews"] - old["total_reviews"]
    dr_pct = 100.0 * dr / max(1, old["total_reviews"])
    dh = new["health_mean"] - old["health_mean"]
    L.append("- **复习负担**: 新 vs 旧 %s %d 次(%.1f%%)——%s。" % (
        "少" if dr < 0 else "多", abs(dr), abs(dr_pct),
        "FSRS 随 S 增长指数拉长间隔, 稳定概念更少被复习" if dr < 0
        else "本组真实 S_real 偏小(忘得快), FSRS 保守调度; 见局限声明"))
    L.append("- **记忆质量**: 全年健康度 新 %.1f%% vs 旧 %.1f%%(%s)；到期真实保持率 新 %.1f%% vs 旧 %.1f%%(目标 %.0f%%)。" % (
        100 * new["health_mean"], 100 * old["health_mean"],
        "新更稳" if dh > 0 else "旧更稳(需结合复习次数看性价比)",
        100 * new["avg_real_at_review"], 100 * old["avg_real_at_review"], 100 * P_TARGET))
    L.append("- **间隔结构**: 新中位 %.0f 天 / P90 %.0f 天 vs 旧 %.0f / %.0f 天——%s。" % (
        new["p50_interval"], new["p90_interval"], old["p50_interval"], old["p90_interval"],
        "新调度更充分地利用已建立的稳定性" if new["p90_interval"] > old["p90_interval"]
        else "两者长间隔接近"))
    L.append("- **局限声明**: ① 二元质量 q∈{1,4} 未覆盖 5 档细分; ② DECAY 用默认 %.2f"
             "(真实库 review_log 现不足 30 条, 校准未生效); ③ 模拟未含新概念学习曲线"
             "与笔记新增节奏, 真实场景以实际使用数据为准。" % forgetting.DECAY_DEFAULT)
    L.append("")
    L.append("## 可复算性")
    L.append("- 种子固定 `SEED = %d`: 复跑 `python scheduler_benchmark.py` 数字逐字节一致。" % SEED)
    L.append("- 公式出处: forgetting.py v2.0 docstring(幂律保持率 / 间隔反解 / S/D 更新)。")
    return "\n".join(L)


def main():
    old = _simulate(_V1Track)
    new = _simulate(_V2Track)
    md = _markdown(old, new)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests_output")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "scheduler_benchmark.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print("\n已落盘: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
