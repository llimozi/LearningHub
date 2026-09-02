# -*- coding: utf-8 -*-
"""cleanup_noise.py —— Phase D-F: 历史知识噪音清理(幂等, 可回滚)

硬约束(D-E 审计护栏):
  - 清理前经 backup.backup_now 备份 + 记录三文件 sha256;
  - 只动数据文件(knowledge/analysis/graph/review_log), 不碰源码笔记/analyzer/复习逻辑/UI;
  - 幂等: 二次运行零改动("缺失即 no-op", 无变更不写盘);
  - 任一校验失败 -> 从备份 zip 恢复三文件并抛错。

用法:
  python cleanup_noise.py            # 执行真实清理(learning_dir='.')
  python cleanup_noise.py <dir>      # 指定学习目录
"""
import hashlib
import json
import os
import sys
import zipfile

DELETE = {"##", "md", "selftest", "交付", "冒烟", "周日", "回归", "调研", "重试"}
MERGE = {"py": "python"}
TOUCHED = ("daily/knowledge.json", "daily/analysis.json", "daily/graph.json")


def _sha256(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _atomic_write(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _load_json(p, default):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _merge_record(src, tgt):
    """py -> python 合并规则(D-F 规格):
    review_count 求和 / last_review_ts 取新 / ease 保留目标值 /
    first_seen 取早 / source_date 取晚。"""
    tgt["review_count"] = int(tgt.get("review_count", 0) or 0) \
        + int(src.get("review_count", 0) or 0)
    st = str(src.get("last_review_ts") or "")
    tt = str(tgt.get("last_review_ts") or "")
    if st and (not tt or st > tt):
        tgt["last_review_ts"] = st
    sf = str(src.get("first_seen") or "")
    tf = str(tgt.get("first_seen") or "")
    if sf and (not tf or sf < tf):
        tgt["first_seen"] = sf
    ss = str(src.get("source_date") or "")
    ts_ = str(tgt.get("source_date") or "")
    if ss and (not ts_ or ss > ts_):
        tgt["source_date"] = ss
    return tgt


def _clean_review_log(log, removed, merged):
    """先重映射合并源(py -> python), 再删孤儿条目(removed 集合)。"""
    out = []
    for e in log or []:
        c = str(e.get("concept") or "")
        if c in merged:
            e["concept"] = merged[c]                     # 合并源条目重映射
            out.append(e)
            continue
        if c in removed:
            continue                                     # 孤儿条目删除
        out.append(e)
    return out


def cleanup_knowledge_noise(learning_dir):
    """执行清理(就地修改数据文件)。返回报告 dict; 幂等(无变更零写盘)。"""
    ld = learning_dir
    kp, ap, gp = (os.path.join(ld, f) for f in TOUCHED)
    pre = {f: _sha256(os.path.join(ld, f)) for f in TOUCHED}
    report = {"pre_sha": pre, "removed": [], "merged_py": False,
              "log_removed": 0, "analysis_concepts_cleaned": 0,
              "graph_rebuilt": False, "changed": False}

    # ---- knowledge.json: 删噪音 + 合并 py -> python + 清 review_log ----
    kd = _load_json(kp, {"version": 1, "knowledge": {}, "review_log": []})
    kn = kd.setdefault("knowledge", {})
    for c in DELETE:
        if c in kn:
            del kn[c]
            report["removed"].append(c)
    if "py" in kn:
        src = kn.pop("py")
        tgt = kn.setdefault("python", {})
        _merge_record(src, tgt)
        report["merged_py"] = True
    removed_log = _clean_review_log(kd.get("review_log", []),
                                    set(report["removed"]), MERGE)
    report["log_removed"] = len(kd.get("review_log", [])) - len(removed_log)
    if report["removed"] or report["merged_py"] or report["log_removed"]:
        kd["review_log"] = removed_log
        _atomic_write(kp, kd)
        report["changed"] = True

    # ---- analysis.json: 清 concepts 里的噪音/合并源 ----
    ad = _load_json(ap, {"notes": {}})
    drop = DELETE | set(MERGE)
    for rec in ad.get("notes", {}).values():
        if isinstance(rec, dict) and isinstance(rec.get("concepts"), list):
            before = len(rec["concepts"])
            rec["concepts"] = [c for c in rec["concepts"] if c not in drop]
            report["analysis_concepts_cleaned"] += before - len(rec["concepts"])
    if report["analysis_concepts_cleaned"]:
        _atomic_write(ap, ad)
        report["changed"] = True

    # ---- graph 重建(仅当概念源有变化) ----
    if report["analysis_concepts_cleaned"]:
        import graph
        graph.build_graph(ld, save=True)
        report["graph_rebuilt"] = True

    report["post_sha"] = {f: _sha256(os.path.join(ld, f)) for f in TOUCHED}
    report["remaining"] = sorted(kn.keys())
    return report


def _restore(backup_path, *paths):
    """从备份 zip 恢复指定文件(整文件快照)。
    arcname 由 backup_items 确定: daily/<文件名>; 不用 relpath(跨盘符会抛 ValueError)。"""
    with zipfile.ZipFile(backup_path) as zf:
        names = set(zf.namelist())
        for p in paths:
            arc = "daily/" + os.path.basename(p)
            if arc in names:
                data = zf.read(arc)
                with open(p, "wb") as f:
                    f.write(data)


def main():
    ld = sys.argv[1] if len(sys.argv) > 1 else "."
    kp, ap, gp = (os.path.join(ld, f) for f in TOUCHED)
    pre = {f: _sha256(os.path.join(ld, f)) for f in TOUCHED}
    import backup
    backup_path = backup.backup_now(ld)
    try:
        report = cleanup_knowledge_noise(ld)
        # 校验: 幂等二次运行必须零变更
        report2 = cleanup_knowledge_noise(ld)
        if report2["changed"]:
            raise RuntimeError("二次运行产生变更: %s" % report2)
        print("CLEANUP OK")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as e:
        _restore(backup_path, kp, ap, gp)
        print("CLEANUP FAILED, 已从备份恢复:", e)
        raise


if __name__ == "__main__":
    main()
