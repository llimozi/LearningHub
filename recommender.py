# -*- coding: utf-8 -*-
r"""recommender.py —— 学习路径推荐 (v1.2 · 纯规则驱动, 无 LLM)

公开 API:
  get_recommendations(learning_dir, today=None, max_items=5)
      -> {"ok", "state": "ready|accumulating", "items": [{type, concept, reason, link}], "context"}

规则(优先级从高到低):
  rest      疲劳态激活 且 近3天完成率较前段回落 -> 只做轻量复习, 不开新内容
            (健康保护永远第一, v1.2 的补弱也排它后面)
  reinforce 掌握分<40 的概念(v1.2 新增) -> 补弱优先;
            理由一句话带齐三要素: 掌握分 / 未复习天数 / 遗忘风险%
  review    「需复习」状态且关联边多的概念 -> 核心薄弱点优先加固
            (reinforce 已命中的概念不再重复出现)
  explore   孤立概念(仅出现1次且无边) -> 写延伸笔记连入知识网络
数据源: tasks.json(fatigue/history) + analysis.json + graph.json
       + daily/knowledge.json(掌握度与遗忘曲线, 缺失时自动退回 v0.9 三规则)
"""
import os
import json
from datetime import date


def _read(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def get_recommendations(learning_dir, today=None, max_items=5):
    today = today or date.today()
    out = []
    state = _read(os.path.join(learning_dir, "tasks.json"), {})
    analysis = _read(os.path.join(learning_dir, "daily", "analysis.json"), {"notes": {}})

    gpath = os.path.join(learning_dir, "daily", "graph.json")
    g = _read(gpath, None)
    if g is None:
        try:
            import graph
            g = graph.build_graph(learning_dir, save=True)
        except Exception:
            g = {"nodes": [], "edges": [], "summary": {}}
    nodes = g.get("nodes", [])
    deg = {n.get("id"): n.get("degree", 0) for n in nodes}

    if not analysis.get("notes") and not nodes:
        return {"ok": True, "state": "accumulating", "items": [],
                "context": {"fatigued": False, "total_concepts": 0}}

    # ---- 规则2(rest): 疲劳 + 完成率回落 ----
    hist = state.get("history", [])[-7:]
    fatigued = bool(state.get("fatigue", {}).get("active"))
    if fatigued and len(hist) >= 4:
        head = [h.get("rate", 0) for h in hist[:3]]
        tail = [h.get("rate", 0) for h in hist[-3:]]
        if tail and head and (sum(tail) / len(tail)) < (sum(head) / len(head)):
            out.append({"type": "rest", "concept": "轻量复习",
                        "reason": "检测到疲劳态且近3天完成率回落——今天只做已巩固概念的闪卡式轻复习, 不开新内容",
                        "link": ""})

    # ---- 规则1.5(reinforce): 掌握分<40 优先补弱 (v1.2 新增) ----
    reinforced = set()
    try:
        import mastery as mastery_mod
        import forgetting as forgetting_mod
        weak = mastery_mod.weak_concepts(learning_dir, top_n=2, today=today)
        kn = forgetting_mod.load_knowledge(learning_dir)["knowledge"]
    except Exception:
        weak, kn = [], {}                                # 无记忆档案=退回 v0.9 行为
    for concept, score in weak:
        rec = kn.get(concept, {})
        ret = forgetting_mod.retention_percent(rec, today=today)
        last = rec.get("last_review_ts") or rec.get("first_seen")
        gap = 0
        if last:
            try:
                gap = (today - date.fromisoformat(str(last)[:10])).days
            except ValueError:
                gap = 0
        link = ("/editor?date=" + rec["source_date"]) if rec.get("source_date") else ""
        out.append({"type": "reinforce", "concept": concept,
                    "reason": "掌握分 %d，已 %d 天未复习，遗忘风险 %d%%——今天先把它拉回安全线" % (
                        score, gap, max(0, 100 - ret)),
                    "link": link})
        reinforced.add(concept)

    # ---- 规则2(review): 需复习 + 关联边多者优先 ----
    try:
        import analyzer
        cards = analyzer.get_review_cards(learning_dir, today=today)
    except Exception:
        cards = []
    need = [c for c in cards if c.get("status") == "需复习"
            and c["concept"] not in reinforced]          # reinforce 已点名的不再重复
    need.sort(key=lambda c: -deg.get(c["concept"], 0))
    for c in need:
        try:
            gap = (today - date.fromisoformat(c["source_date"])).days
        except Exception:
            gap = 0
        d = deg.get(c["concept"], 0)
        out.append({"type": "review", "concept": c["concept"],
                    "reason": "距上次出现 " + str(gap) + " 天 · 关联 " + str(d) + " 条边——核心薄弱点优先加固",
                    "link": "/editor?date=" + c["source_date"]})

    # ---- 规则3(explore): 孤立概念 ----
    lonely = [nd for nd in nodes if nd.get("count", 0) == 1 and nd.get("degree", 0) == 0
              and nd.get("id", "") not in reinforced]    # reinforce 已点名的不再重复
    for nd in lonely[:3]:
        dss = nd.get("dates") or [""]
        out.append({"type": "explore", "concept": nd.get("id", ""),
                    "reason": "孤立概念——写一篇延伸笔记把它连进知识网络",
                    "link": "/editor?date=" + dss[-1]})

    seen = set()
    final = []
    for r in out:
        key = (r["type"], r["concept"])
        if key in seen:
            continue
        seen.add(key)
        final.append(r)
        if len(final) >= max_items:
            break
    return {"ok": True, "state": "ready", "items": final,
            "context": {"fatigued": fatigued, "total_concepts": len(nodes)}}
