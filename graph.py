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
