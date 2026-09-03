# -*- coding: utf-8 -*-
"""graph.py —— 知识点共现图谱 (v0.8 · 纯标准库)

公开 API:
  build_graph(learning_dir, save=True) -> {"nodes","edges","summary"}  # 读 analysis.json 重算并可落盘
  load_graph(learning_dir)             -> dict | None                  # 读 daily/graph.json(空图返回 None)

节点: {"id","count"(出现天数),"dates",[...],"degree"(连接数)}
边:   {"source","target","weight"}   权重 = 两概念同篇共现的笔记数(按字母序去重方向)
"""
import os
import re
import json
from datetime import date

_JUNK_RE = re.compile(r"^[\\\W_]+$")          # 纯符号/纯标点(如 ## 、-- 、**)视为噪声


def _analysis_path(d):
    return os.path.join(d, "daily", "analysis.json")


def _graph_path(d):
    return os.path.join(d, "daily", "graph.json")


def build_graph(learning_dir, save=True):
    ap = _analysis_path(learning_dir)
    if not os.path.exists(ap):
        g = {"nodes": [], "edges": [],
             "summary": {"total_concepts": 0, "total_edges": 0, "core": None,
                         "generated": date.today().isoformat()}}
        if save:
            _save(learning_dir, g)
        return g
    with open(ap, encoding="utf-8-sig") as f:
        data = json.load(f)
    notes = data.get("notes", {})
    node_dates = {}
    pair_count = {}
    for ds in sorted(notes.keys()):
        concepts = []                                   # 同篇内去重, 保持顺序
        for c in notes[ds].get("concepts", []):
            c = str(c).strip().lower()               # v0.9: 噪声过滤职责已回归 analyzer.py
            if c not in concepts:
                concepts.append(c)
        for c in concepts:
            node_dates.setdefault(c, []).append(ds)
        for i in range(len(concepts)):
            for j in range(i + 1, len(concepts)):
                a, b = sorted((concepts[i], concepts[j]))
                pair_count[(a, b)] = pair_count.get((a, b), 0) + 1
    nodes = [{"id": c, "count": len(dss), "dates": dss}
             for c, dss in sorted(node_dates.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    edges = [{"source": a, "target": b, "weight": w}
             for (a, b), w in sorted(pair_count.items(), key=lambda kv: -kv[1])]
    degree = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    for nd in nodes:
        nd["degree"] = degree.get(nd["id"], 0)
    core = None
    if nodes:
        core = max(nodes, key=lambda x: (x.get("degree", 0), x["count"]))["id"]
    g = {"nodes": nodes, "edges": edges,
         "summary": {"total_concepts": len(nodes), "total_edges": len(edges),
                     "core": core, "generated": date.today().isoformat()}}
    if save:
        _save(learning_dir, g)
    return g


def load_graph(learning_dir):
    gp = _graph_path(learning_dir)
    if os.path.exists(gp):
        try:
            with open(gp, encoding="utf-8-sig") as f:
                g = json.load(f)
            if g.get("nodes"):
                return g
        except Exception:
            pass
    return None


def _save(learning_dir, g):
    with open(_graph_path(learning_dir), "w", encoding="utf-8-sig") as f:
        json.dump(g, f, ensure_ascii=False, indent=2)


# ================= Phase B2: 跨概念语义关联增强(可选 LLM) =================
_REL_CACHE_KEY = "semantic_rels"          # knowledge.json 顶层缓存键(避免重复调 API)
_SEMANTIC_BATCH = 10                      # 每批最多概念对


def _knowledge_path(d):
    return os.path.join(d, "daily", "knowledge.json")


def load_semantic_rels(learning_dir):
    """读语义关系缓存(knowledge.json 顶层 semantic_rels); 无则空 dict。"""
    try:
        with open(_knowledge_path(learning_dir), encoding="utf-8-sig") as f:
            data = json.load(f)
        rels = data.get(_REL_CACHE_KEY)
        return rels if isinstance(rels, dict) else {}
    except Exception:
        return {}


def _save_semantic_rels(learning_dir, rels):
    """写回缓存: 仅更新 semantic_rels 键, 不动其他记忆字段(原子 tmp+replace)。"""
    p = _knowledge_path(learning_dir)
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        data = {"version": 2, "knowledge": {}}
    data[_REL_CACHE_KEY] = rels
    tmp = p + ".tmp"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def enrich_relations(learning_dir, graph=None, max_pairs=None):
    """用 LLM 把共现边升级为语义关系(上位/下位/相关/前置), 结果缓存到 knowledge.json。

    协议(2026-09-03 用户盯防项):
      - 带缓存: 已判定过的概念对(缓存命中)绝不重复调 API;
      - 批量限制: 每轮最多 batch 10 对, 全量分批处理(受 max_pairs 上限约束, 默认不限);
      - 无 Key / 熔断 / 失败: 静默返回已有缓存(调用方回退共现), 零二次调用。
    返回 {"rels": {...缓存}, "processed": n(本次新判定对数), "cached_total": n(缓存总对数)}。
    """
    try:
        import analyzer
        if graph is None:
            graph = build_graph(learning_dir, save=False)
    except Exception:
        return {"rels": {}, "processed": 0, "cached_total": 0}
    rels = load_semantic_rels(learning_dir)
    # 候选: 共现边中尚未判定的对(概念名与 build_graph 一致: 小写规范化)
    candidates = []
    for e in graph.get("edges", []):
        a = str(e.get("source") or "").strip().lower()
        b = str(e.get("target") or "").strip().lower()
        if not a or not b:
            continue
        key = a + "||" + b
        if key in rels or b + "||" + a in rels:
            continue
        if any(c["a"] == a and c["b"] == b for c in candidates):
            continue
        candidates.append({"a": a, "b": b})
        if max_pairs is not None and len(candidates) >= max_pairs:
            break
    if not candidates:
        return {"rels": rels, "processed": 0, "cached_total": len(rels)}
    processed = 0
    for i in range(0, len(candidates), _SEMANTIC_BATCH):
        batch = candidates[i:i + _SEMANTIC_BATCH]
        try:
            out = analyzer.llm_concept_relations(batch)
        except Exception:
            break                                     # 熔断/异常: 停批, 保留已缓存
        if not out:
            break                                     # 无 Key/熔断/失败 -> 静默停
        for r in out.get("rels", []):
            a = str(r.get("a") or "").strip().lower()
            b = str(r.get("b") or "").strip().lower()
            t = r.get("type")
            if not a or not b or not t:
                continue
            rels[a + "||" + b] = t
        processed += len(batch)
    if processed:
        _save_semantic_rels(learning_dir, rels)
    return {"rels": rels, "processed": processed, "cached_total": len(rels)}
