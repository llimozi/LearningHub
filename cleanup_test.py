# -*- coding: utf-8 -*-
"""cleanup_test.py —— Phase D-F 历史噪音清理聚焦测试
跑法A: pytest cleanup_test.py   跑法B: python cleanup_test.py (零依赖runner)
覆盖(D-F 规格):
  1 确认噪音删除 / 2 py->python 合并 / 3 复习史保留 / 4 analysis 源清理 /
  5 review_log 清理 / 6 graph 重建 / 7 任务引用不破坏 / 8 归一化同步后不复活 /
  9 备份回滚 / 10 幂等二次运行零变更
全部使用临时目录模拟, 不触碰生产数据。
"""
import datetime
import hashlib
import json
import os
import shutil
import tempfile

import cleanup_noise
import forgetting


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _mk_ld():
    """构造与生产同构的临时学习目录。"""
    d = tempfile.mkdtemp(prefix="cln_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    # analysis.json(与生产 08-22/08-23 同构)
    analysis = {"notes": {
        "2026-08-22": {"topic": "学习日志", "concepts": ["交付", "py", "selftest", "冒烟", "回归"],
                       "tags": ["项目工程", "python", "复习自测"], "code_langs": []},
        "2026-08-23": {"topic": "学习日志", "concepts": ["复盘", "调研", "trending", "重试", "周日"],
                       "tags": ["调研", "agent", "复盘"], "code_langs": []},
    }}
    with open(os.path.join(d, "daily", "analysis.json"), "w", encoding="utf-8-sig") as f:
        json.dump(analysis, f, ensure_ascii=False)
    # knowledge.json(17 概念同生产)
    kn = {}
    for c in ("##", "api", "md", "py", "selftest", "trending", "交付", "冒烟", "周日",
              "回归", "复盘", "调研", "重试"):
        kn[c] = {"first_seen": "2026-08-22" if c not in ("周日", "复盘", "调研", "重试", "trending") else "2026-08-23",
                 "source_date": kn[c]["first_seen"] if False else "2026-08-22",
                 "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}
    kn["##"]["review_count"] = 1
    kn["##"]["last_review_ts"] = "2026-08-23T09:00:00"
    kn["api"]["review_count"] = 1
    kn["api"]["last_review_ts"] = "2026-08-23T09:00:00"
    kn["py"]["review_count"] = 1
    kn["py"]["last_review_ts"] = "2026-08-27T10:00:00"
    kn["selftest"]["review_count"] = 1
    kn["selftest"]["last_review_ts"] = "2026-08-27T10:00:00"
    kn["周日"]["review_count"] = 2
    kn["周日"]["last_review_ts"] = "2026-08-27T10:00:00"
    kn["py"]["source_date"] = "2026-08-22"
    kn["python"] = {"first_seen": "2026-08-22", "source_date": "2026-08-22",
                    "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}
    kn["agent"] = {"first_seen": "2026-08-23", "source_date": "2026-08-23",
                   "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}
    kn["复习自测"] = {"first_seen": "2026-08-22", "source_date": "2026-08-22",
                     "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}
    kn["项目工程"] = {"first_seen": "2026-08-22", "source_date": "2026-08-22",
                      "last_review_ts": None, "review_count": 0, "ease_factor": 2.5}
    kd = {"version": 1, "knowledge": kn,
          "review_log": [{"ts": "2026-08-23T09:00:00", "concept": "##", "quality": 4},
                         {"ts": "2026-08-23T09:00:00", "concept": "api", "quality": 4},
                         {"ts": "2026-08-27T10:00:00", "concept": "selftest", "quality": 4},
                         {"ts": "2026-08-27T10:00:00", "concept": "py", "quality": 4},
                         {"ts": "2026-08-27T10:00:00", "concept": "周日", "quality": 4},
                         {"ts": "2026-08-27T10:00:00", "concept": "周日", "quality": 4}]}
    with open(os.path.join(d, "daily", "knowledge.json"), "w", encoding="utf-8-sig") as f:
        json.dump(kd, f, ensure_ascii=False)
    # tasks.json: 一条含 review_concept 的正常任务(引用保留概念) + 一条无元数据任务
    tasks = {"version": 2, "days": {"2099-01-01": [
        {"id": "t1", "text": "复习：Agent", "done": False, "review_concept": "agent",
         "review_source_date": "2099-01-01"}]}, "log": []}
    with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8-sig") as f:
        json.dump(tasks, f, ensure_ascii=False)
    # 预建 graph.json(与生产同构)
    import graph
    graph.build_graph(d, save=True)
    return d


def _load(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


# ---------- 1. 确认噪音删除 ----------
def test_1_confirmed_noise_deleted():
    d = _mk_ld()
    rep = cleanup_noise.cleanup_knowledge_noise(d)
    kn = _load(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
    for c in ("##", "md", "selftest", "交付", "冒烟", "周日", "回归", "调研", "重试"):
        assert c not in kn, c
    assert set(rep["removed"]) == {"##", "md", "selftest", "交付", "冒烟",
                                   "周日", "回归", "调研", "重试"}, rep


# ---------- 2. py -> python 合并 ----------
def test_2_merge_py_to_python():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    kn = _load(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
    assert "py" not in kn, "py 应被合并移除"
    assert "python" in kn, "python 应保留"
    assert kn["python"]["review_count"] == 1, kn["python"]
    assert kn["python"]["last_review_ts"] == "2026-08-27T10:00:00", kn["python"]


# ---------- 3. 复习史保留 ----------
def test_3_review_history_preserved():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    kn = _load(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
    p = kn["python"]
    assert p["review_count"] == 1, p                     # 0 + 1 = 1
    assert p["last_review_ts"] == "2026-08-27T10:00:00", p   # 取 py 的较新
    assert p["ease_factor"] == 2.5, p                    # 保留目标值
    assert p["first_seen"] == "2026-08-22", p            # 取早
    assert p["source_date"] == "2026-08-22", p           # 取晚(均同)


# ---------- 4. analysis 源清理 ----------
def test_4_analysis_cleaned():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    a = _load(os.path.join(d, "daily", "analysis.json"))["notes"]
    assert a["2026-08-22"]["concepts"] == [], a["2026-08-22"]
    assert a["2026-08-23"]["concepts"] == ["复盘", "trending"], a["2026-08-23"]
    # tags 保留(不动)
    assert "python" in a["2026-08-22"]["tags"], a["2026-08-22"]


# ---------- 5. review_log 清理 ----------
def test_5_review_log_cleaned():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    kd = _load(os.path.join(d, "daily", "knowledge.json"))
    log = kd["review_log"]
    concepts = {e["concept"] for e in log}
    assert concepts == {"api", "python"}, log          # api 保留, py 重映射 python
    assert not any(e["concept"] in ("##", "selftest", "周日") for e in log), log


# ---------- 6. graph 重建 ----------
def test_6_graph_rebuilt():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    g = _load(os.path.join(d, "daily", "graph.json"))
    ids = {n.get("id") for n in g.get("nodes", [])}
    assert not ids & {"##", "md", "selftest", "交付", "冒烟", "周日", "回归",
                      "调研", "重试", "py"}, ids
    assert "复盘" in ids and "trending" in ids, ids


# ---------- 7. 任务引用不破坏 ----------
def test_7_no_task_breakage():
    d = _mk_ld()
    before = _load(os.path.join(d, "tasks.json"))
    cleanup_noise.cleanup_knowledge_noise(d)
    after = _load(os.path.join(d, "tasks.json"))
    assert after == before, "tasks.json 不应被清理改动"
    # 无任务引用被删除概念; 保留概念的任务引用完好
    kn = _load(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
    for dk, bucket in after["days"].items():
        for t in bucket:
            rc = str(t.get("review_concept", ""))
            assert rc in kn or not rc, (rc, t)
    assert "agent" in kn, "保留概念不应被删除"


# ---------- 8. 归一化同步后不复活 ----------
def test_8_no_resurrection_after_sync():
    d = _mk_ld()
    cleanup_noise.cleanup_knowledge_noise(d)
    forgetting.sync_from_analysis(d, today=datetime.date(2026, 9, 1), normalize=True)
    kn = _load(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
    for c in ("##", "md", "selftest", "交付", "冒烟", "周日", "回归", "调研", "重试", "py"):
        assert c not in kn, c


# ---------- 9. 备份回滚 ----------
def test_9_rollback_from_backup():
    import backup
    d = _mk_ld()
    kp = os.path.join(d, "daily", "knowledge.json")
    ap = os.path.join(d, "daily", "analysis.json")
    gp = os.path.join(d, "daily", "graph.json")
    pre = {p: _sha(p) for p in (kp, ap, gp)}
    bpath = backup.backup_now(d)                        # 清理前备份(回滚源)
    cleanup_noise.cleanup_knowledge_noise(d)
    assert _sha(kp) != pre[kp], "清理应改变 knowledge.json"
    # 人为破坏后从清理前备份回滚
    with open(kp, "w", encoding="utf-8-sig") as f:
        f.write("{broken")
    cleanup_noise._restore(bpath, kp, ap, gp)
    assert _sha(kp) == pre[kp], "回滚后 knowledge.json 应等于清理前"
    assert _sha(ap) == pre[ap], "回滚后 analysis.json 应等于清理前"
    assert _sha(gp) == pre[gp], "回滚后 graph.json 应等于清理前"


# ---------- 10. 幂等二次运行 ----------
def test_10_idempotent_second_run():
    d = _mk_ld()
    rep1 = cleanup_noise.cleanup_knowledge_noise(d)
    kp = os.path.join(d, "daily", "knowledge.json")
    ap = os.path.join(d, "daily", "analysis.json")
    gp = os.path.join(d, "daily", "graph.json")
    sha1 = {p: _sha(p) for p in (kp, ap, gp)}
    rep2 = cleanup_noise.cleanup_knowledge_noise(d)
    assert rep2["changed"] is False, rep2
    assert {p: _sha(p) for p in (kp, ap, gp)} == sha1, "二次运行应零写盘零变更"
    assert rep1["removed"] == rep2["removed"] or rep2["removed"] == [], rep2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
        except Exception as ex:
            failed += 1
            print("ERROR", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    import sys
    sys.exit(1 if failed else 0)
