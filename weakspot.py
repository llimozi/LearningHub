# -*- coding: utf-8 -*-
r"""weakspot.py —— 周日薄弱环节自动分析 (v1.2 · 纯标准库)

规格(v1.2): 每周日跑一次分析——找掌握分最低的 5 个知识点(须 <40 进红队),
生成「薄弱点专项练习」建议并插入下周任务库。

触发与幂等设计:
  - 只在 weekday()==6(周日) 执行, 其余日期直接跳过;
  - 幂等键 = 报告文件名 weakness_{下周周一}.md——文件存在即本周已分析,
    不引入任何额外状态文件(沿用 lessons #005: 键只在一处生成);
  - 任务 id = "w-" + 概念名 md5 前 8 位, **确定性 id**:
    同概念跨桶/跨周天然去重, 手工排过的同款也不会重复插。

插入规则: 目标桶 = 下周一; 同 id 已在全库任何桶出现 -> skipped;
新任务 priority=1(专项练习高优), src_date=目标日, 并向 tasks.log 记一笔。
全员健康(无 <40)时照常立报告写「无薄弱点」, 但不插任务。

公开 API:
  task_id(concept) -> str
  weekly_analysis(learning_dir, today=None, max_items=5)
      -> {ran, already_done, reason, report, concepts, added, skipped}
"""
import datetime
import hashlib
import json
import os

import mastery
from reportio import REPORTS_DIR

THRESHOLD = mastery.WEAK_THRESHOLD
TOP_N = 5


def _rdir(learning_dir):
    return os.path.join(learning_dir, REPORTS_DIR)


def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def task_id(concept):
    """确定性任务 id: 跨天跨周稳定, 是去重的基石"""
    return "w-" + hashlib.md5(concept.encode("utf-8")).hexdigest()[:8]


def _task_text(concept, score):
    return "📌 专项练习：%s（掌握分 %d）——重读笔记 + 口述自测，≤15min" % (concept, score)


def insert_weakness_tasks(learning_dir, scored_concepts, target_date, today=None):
    """把 [(concept,score)] 插入 target_date 桶; 全库同 id 去重。返回 {added, skipped}。"""
    p = os.path.join(learning_dir, "tasks.json")
    st = _load(p, {})
    if not isinstance(st, dict):
        st = {}
    days = st.setdefault("days", {})
    have = set()
    for bucket in days.values():
        for t in bucket:
            if isinstance(t, dict) and t.get("id"):
                have.add(t["id"])
    bucket = days.setdefault(target_date.isoformat(), [])
    bucket_ids = {t.get("id") for t in bucket if isinstance(t, dict)}
    added, skipped = [], []
    for concept, score in scored_concepts:
        tid = task_id(concept)
        if tid in have or tid in bucket_ids:
            skipped.append(concept)
            continue
        bucket.append({"id": tid, "text": _task_text(concept, score),
                       "done": False, "carried": False,
                       "src_date": target_date.isoformat(), "priority": 1})
        have.add(tid)
        bucket_ids.add(tid)
        added.append(concept)
    if added:
        t = today or datetime.date.today()
        st.setdefault("log", []).append({
            "date": t.isoformat(), "event": "weakness_insert",
            "to": target_date.isoformat(),
            "ids": [task_id(c) for c in added],
            "desc": "周日薄弱点分析插入 %d 条专项练习" % len(added)})
        _write_json(p, st)
    return {"added": added, "skipped": skipped}


def _report_markdown(target_date, rows, inserted_n):
    now_s = datetime.datetime.now().isoformat(timespec="seconds")
    head = ("# 薄弱点专项分析 · 下周 %s 起\n\n"
            "> 生成于 %s · 掌握分<%d 自动入选（新概念保护期不计入）\n\n"
            % (target_date.isoformat(), now_s, THRESHOLD))
    if not rows:
        return head + "## 结论\n\n- ✅ 无薄弱点——当前所有知识点掌握分都在安全线上，继续保持\n"
    table = ["| 知识点 | 掌握分 | 最近复习 | 出现笔记 |",
             "|---|---|---|---|"]
    for concept, score, last_txt, notes_n in rows:
        table.append("| %s | %d | %s | %d 篇 |" % (concept, score, last_txt, notes_n))
    return (head + "## 本周最低 Top%d\n\n" % len(rows)
            + "\n".join(table) + "\n\n## 练习建议\n"
            + "- 已按上表插入 **%d** 条专项练习到下周任务库（P1 高优）\n" % inserted_n
            + "- 每条 ≤15min：重读对应笔记 → 合上口述核心 → 自测一题\n"
            + "- 打卡复习后掌握分会自动回升，连续两周达标即可移出本队列\n")


def weekly_analysis(learning_dir, today=None, max_items=TOP_N):
    """周日入口: 分析+立报告+插任务。非周日或已做过则安全跳过。"""
    today = today or datetime.date.today()
    out = {"ran": False, "already_done": False, "reason": "",
           "report": None, "concepts": [], "added": [], "skipped": []}
    if today.weekday() != 6:
        out["reason"] = "仅周日运行"
        return out
    target = today + datetime.timedelta(days=1)          # 周日的「明天」就是下周周一
    rname = "weakness_" + target.strftime("%Y%m%d") + ".md"
    rp = os.path.join(_rdir(learning_dir), rname)
    if os.path.exists(rp):                               # 幂等键=报告文件本身
        out["already_done"] = True
        out["reason"] = "本周已分析(" + rname + ")"
        out["report"] = rname
        return out

    scores = mastery.update_mastery_scores(learning_dir, today=today)
    weak = mastery.weak_concepts(learning_dir, top_n=max_items, today=today)[:max_items]

    counts = mastery._appear_counts(learning_dir)        # 出现篇数进表格
    kn = mastery.forgetting.load_knowledge(learning_dir)["knowledge"]
    rows = []
    for concept, score in weak:
        rec = kn.get(concept, {})
        last = rec.get("last_review_ts")
        rows.append((concept, score,
                     (str(last)[:10] if last else "从未"),
                     counts.get(concept, 0)))

    ins = insert_weakness_tasks(learning_dir, weak, target, today=today) if weak \
        else {"added": [], "skipped": []}

    os.makedirs(_rdir(learning_dir), exist_ok=True)
    with open(rp, "w", encoding="utf-8-sig") as f:
        f.write(_report_markdown(target, rows, len(ins["added"])))

    out.update({"ran": True, "report": rname,
                "concepts": [c for c, _s in weak],
                "added": ins["added"], "skipped": ins["skipped"]})
    return out
