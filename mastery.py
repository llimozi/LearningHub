# -*- coding: utf-8 -*-
r"""mastery.py —— 知识点掌握度模型 (v1.2 · 纯标准库)

输出 0~100 掌握分(mastery_score), 写回记忆档案 daily/knowledge.json
(v1.1 已确立「写入权唯一化」: analysis.json 只读, 本模块只碰 knowledge.json)。

四因子合成(v1.2 规格: 复习次数/遗忘曲线位置/关联笔记数/最近测试正确率):
  复习次数   min(review_count,6)/6 × 30 分        —— 6 次封顶, 多刷不涨分
  保持率     forgetting.retention_percent × 0.45  —— 遗忘曲线位置占最大头(45 分)
  关联笔记数 min(出现篇数,5)/5 × 25 分            —— 5 篇封顶
  测验正确率 可选因子(last_quiz_accuracy∈[0,1]):
             有值时其余三因子按 90% 缩放后 + 正确率×10;
             无值时不惩罚、不占权重(系统尚无测验数据源, 如实降级为三因子模型)
掌握分 < WEAK_THRESHOLD(40) 自动进入「重点攻克」队列(weak_concepts),
图谱节点配色与路径推荐第四规则(补弱优先)都消费这份分数。

公开 API:
  mastery_score(record, note_count=0, today=None) -> int      # 单概念纯函数
  compute_all(learning_dir, today=None)           -> {concept: score}   # 只算不写
  update_mastery_scores(learning_dir, today=None) -> {concept: score}   # 算并写回(幂等)
  weak_concepts(learning_dir, threshold=40, top_n=None, today=None)
                                                  -> [(concept, score)] 升序
"""
import datetime

import forgetting

WEIGHT_REVIEW = 30
WEIGHT_RETENTION = 45
WEIGHT_NOTES = 25
WEIGHT_QUIZ = 10
REVIEW_CAP = 6
NOTES_CAP = 5
WEAK_THRESHOLD = 40
NEWCOMER_FLOOR = 50                                   # 未复习且未逾期的新概念中性下限


def _clamp_int(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


def mastery_score(record, note_count=0, today=None):
    """单概念掌握分纯函数。record 为 knowledge.json 单条档案。
    新概念保护期: 从未复习且尚未逾期(D+1 未过)的概念不判弱——
    「薄弱环节」指荒废, 不是「还没轮到第一次复习」; 一旦逾期立即按曲线正常判定。"""
    today = today or datetime.date.today()
    rc = _clamp_int(record.get("review_count", 0), 0, REVIEW_CAP)
    s_review = (rc / REVIEW_CAP) * WEIGHT_REVIEW

    retention = forgetting.retention_percent(record, today=today)
    s_retention = (retention / 100.0) * WEIGHT_RETENTION

    nn = _clamp_int(note_count, 0, NOTES_CAP)
    s_notes = (nn / NOTES_CAP) * WEIGHT_NOTES

    score = s_review + s_retention + s_notes
    q = record.get("last_quiz_accuracy")
    if isinstance(q, (int, float)) and not isinstance(q, bool) and 0 <= q <= 1:
        score = score * ((100 - WEIGHT_QUIZ) / 100.0) + float(q) * WEIGHT_QUIZ
    score = max(0, min(100, int(round(score))))

    if not record.get("last_review_ts"):
        first = _parse_day(record.get("first_seen"))
        if first is not None:
            overdue = (today - first).days - forgetting.INTERVALS[0]
            if overdue <= 0 and score < NEWCOMER_FLOOR:
                score = NEWCOMER_FLOOR                       # 保护期内不低于中性线
    return score


def _parse_day(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _appear_counts(learning_dir):
    """概念 -> 出现篇数(口径与图谱 count 一致: 一天一篇去重)"""
    import analyzer
    notes = analyzer.load_analysis(learning_dir).get("notes", {})
    counts = {}
    for ds, rec in notes.items():
        if not isinstance(rec, dict):
            continue
        for c in set(str(x).strip() for x in (rec.get("concepts") or []) if str(x).strip()):
            counts[c] = counts.get(c, 0) + 1
    return counts


def compute_all(learning_dir, today=None):
    """全量计算但不落盘——图谱接口等高频读取方走这里"""
    today = today or datetime.date.today()
    kn = forgetting.load_knowledge(learning_dir)["knowledge"]
    counts = _appear_counts(learning_dir)
    return {c: mastery_score(rec, counts.get(c, 0), today)
            for c, rec in kn.items()}


def update_mastery_scores(learning_dir, today=None):
    """计算并把 mastery_score 写回记忆档案(幂等: 无变化零写盘)。返回分数表。"""
    today = today or datetime.date.today()
    data = forgetting.load_knowledge(learning_dir)
    kn = data["knowledge"]
    counts = _appear_counts(learning_dir)
    scores = {}
    changed = False
    for c, rec in kn.items():
        v = mastery_score(rec, counts.get(c, 0), today)
        scores[c] = v
        if rec.get("mastery_score") != v:
            rec["mastery_score"] = v
            changed = True
    if changed:
        forgetting.save_knowledge(learning_dir, data)
    return scores


def weak_concepts(learning_dir, threshold=WEAK_THRESHOLD, top_n=None, today=None):
    """重点攻克队列: 掌握分 < threshold 的概念, 越危险越靠前"""
    scores = update_mastery_scores(learning_dir, today=today)
    items = [(c, s) for c, s in scores.items() if s < threshold]
    items.sort(key=lambda x: (x[1], x[0]))
    if top_n:
        items = items[:top_n]
    return items
