# -*- coding: utf-8 -*-
"""transfer_test.py —— 手动导入/导出单元测试 (v1.1 · 纯标准库)
跑法A: pytest transfer_test.py      跑法B: python transfer_test.py (零依赖runner)
覆盖: 导出三件套打包与缺文件容错 / 导入校验拒收 / 同id覆盖新id追加 /
      history按日期合并 / 台账合并后图谱自动重建 / 导入前强制备份(旧内容可从zip验尸) /
      坏段落跳过并告警 / 干净目录整包回灌(roundtrip)。
"""
import datetime
import json
import os
import shutil
import tempfile
import zipfile

import transfer
from backup import BACKUP_DIR_NAME

NOW = datetime.datetime(2099, 7, 1, 9, 0, 0)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _dir_with_tasks(days, history=None):
    d = tempfile.mkdtemp()
    st = {"version": 3, "days": days,
          "history": history or [], "log": []}
    _write(os.path.join(d, "tasks.json"), st)
    return d


# ---------------- 导出 ----------------
def test_export_contains_core_sections():
    d = _dir_with_tasks({"2099-07-01": [{"id": "t1", "text": "x", "done": False}]})
    try:
        _write(os.path.join(d, "daily", "analysis.json"), {"notes": {"2099-07-01": {"concepts": ["a"]}}})
        _write(os.path.join(d, "daily", "graph.json"), {"nodes": [], "edges": []})
        b = transfer.export_bundle(d, now=NOW)
        assert b["kind"] == "full-export" and b["version"] == 1
        assert b["exported_at"] == NOW.isoformat(timespec="seconds")
        assert set(b["data"].keys()) >= {"tasks.json", "daily/analysis.json", "daily/graph.json"}
        assert b["data"]["tasks.json"]["days"]["2099-07-01"][0]["id"] == "t1"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_export_skips_missing_files():
    d = tempfile.mkdtemp()
    try:
        b = transfer.export_bundle(d, now=NOW)
        assert b["data"] == {}, "空目录导出应得到空数据段而非报错"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 校验 ----------------
def test_import_rejects_invalid_bundles_without_side_effects():
    d = _dir_with_tasks({})
    try:
        before = _read(os.path.join(d, "tasks.json"))
        for bad in (None, "字符串", {"kind": "full-export"},          # 缺 data
                    {"kind": "别的格式", "data": {}}):                 # 不认识的格式
            out = transfer.import_bundle(d, bad, now=NOW)
            assert out["ok"] is False, (bad, out)
        assert _read(os.path.join(d, "tasks.json")) == before, "拒收时不得动真实文件"
        assert not os.path.exists(os.path.join(d, BACKUP_DIR_NAME)), \
            "校验失败连备份都不该做"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 任务合并 ----------------
def test_import_tasks_same_id_overwrite_new_id_append():
    d = _dir_with_tasks({
        "2099-07-01": [{"id": "t1", "text": "旧版任务一", "done": False}],
    })
    try:
        bundle = {"kind": "full-export", "data": {"tasks.json": {
            "days": {
                "2099-07-01": [{"id": "t1", "text": "新版任务一", "done": True},
                               {"id": "t2", "text": "新任务二", "done": False}],
                "2099-07-02": [{"id": "t3", "text": "新一天任务", "done": False}],
            },
            "history": [], "log": [],
        }}}
        out = transfer.import_bundle(d, bundle, now=NOW)
        assert out["ok"] is True, out
        st = _read(os.path.join(d, "tasks.json"))
        b1 = {t["id"]: t for t in st["days"]["2099-07-01"]}
        assert b1["t1"]["text"] == "新版任务一" and b1["t1"]["done"] is True
        assert "t2" in b1
        assert any(t["id"] == "t3" for t in st["days"]["2099-07-02"])
        sec = out["sections"]["tasks"]
        assert sec["added"] == 2 and sec["overwritten"] == 1, sec
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_history_merged_by_date():
    d = _dir_with_tasks({}, history=[{"date": "2099-06-30", "total": 3, "done": 0, "rate": 0.0}])
    try:
        bundle = {"kind": "full-export", "data": {"tasks.json": {
            "days": {},
            "history": [
                {"date": "2099-06-30", "total": 3, "done": 3, "rate": 1.0},   # 同日覆盖
                {"date": "2099-07-01", "total": 2, "done": 1, "rate": 0.5}],  # 新日追加
            "log": [],
        }}}
        transfer.import_bundle(d, bundle, now=NOW)
        hist = {h["date"]: h for h in _read(os.path.join(d, "tasks.json"))["history"]}
        assert hist["2099-06-30"]["rate"] == 1.0 and "2099-07-01" in hist
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 台账与图谱 ----------------
def test_import_notes_merge_then_graph_rebuilt():
    d = _dir_with_tasks({})
    try:
        _write(os.path.join(d, "daily", "analysis.json"),
               {"notes": {"2099-06-30": {"topic": "旧", "concepts": ["python"], "tags": [], "code_langs": []}}})
        bundle = {"kind": "full-export", "data": {
            "daily/analysis.json": {"notes": {
                "2099-06-30": {"topic": "新", "concepts": ["mcp"], "tags": [], "code_langs": []},
                "2099-07-01": {"topic": "增", "concepts": ["rag"], "tags": [], "code_langs": []}}},
        }}
        out = transfer.import_bundle(d, bundle, now=NOW)
        assert out["ok"] is True
        notes = _read(os.path.join(d, "daily", "analysis.json"))["notes"]
        assert notes["2099-06-30"]["concepts"] == ["mcp"]       # 同日覆盖
        assert notes["2099-07-01"]["concepts"] == ["rag"]       # 新日追加
        g = _read(os.path.join(d, "daily", "graph.json"))       # 图谱按合并后台账重建
        gnames = {n["id"] for n in g["nodes"]}
        assert {"mcp", "rag"} <= gnames and "python" not in gnames
        assert out["sections"]["graph"] == "rebuilt", out["sections"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_graph_only_taken_wholesale_when_no_analysis():
    d = _dir_with_tasks({})
    try:
        bundle = {"kind": "full-export", "data": {
            "daily/graph.json": {"nodes": [{"id": "x", "count": 1, "dates": ["2099-07-01"], "degree": 0}],
                                 "edges": [], "summary": {}}}}
        out = transfer.import_bundle(d, bundle, now=NOW)
        g = _read(os.path.join(d, "daily", "graph.json"))
        assert g["nodes"][0]["id"] == "x"
        assert out["sections"]["graph"] == "from_bundle"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_knowledge_section_merges_by_concept():
    d = _dir_with_tasks({})
    try:
        _write(os.path.join(d, "daily", "knowledge.json"),
               {"knowledge": {"k1": {"review_count": 9}}})
        bundle = {"kind": "full-export", "data": {
            "daily/knowledge.json": {"knowledge": {
                "k1": {"review_count": 3},                      # 同名覆盖
                "k2": {"review_count": 1}}}}}                   # 新名追加
        out = transfer.import_bundle(d, bundle, now=NOW)
        kn = _read(os.path.join(d, "daily", "knowledge.json"))["knowledge"]
        assert kn["k1"]["review_count"] == 3 and kn["k2"]["review_count"] == 1
        assert out["sections"]["knowledge"]["added"] == 1
        assert out["sections"]["knowledge"]["overwritten"] == 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 备份先行 ----------------
def test_import_backs_up_old_data_before_touching_anything():
    d = _dir_with_tasks({"2099-07-01": [{"id": "old", "text": "导入前的老数据标记", "done": False}]})
    try:
        bundle = {"kind": "full-export", "data": {"tasks.json": {
            "days": {"2099-07-01": [{"id": "old", "text": "导入后的新数据", "done": True}]},
            "history": [], "log": []}}}
        out = transfer.import_bundle(d, bundle, now=NOW)
        assert out["ok"] is True and out["backup"]
        bdir = os.path.join(d, BACKUP_DIR_NAME)
        zips = sorted(n for n in os.listdir(bdir) if n.endswith(".zip"))
        assert zips, "导入前必须留备份"
        with zipfile.ZipFile(os.path.join(bdir, zips[-1])) as zf:
            old_snapshot = zf.read("tasks.json").decode("utf-8")
            assert "导入前的老数据标记" in old_snapshot, "备份必须是导入前的状态"
            assert "导入后的新数据" not in old_snapshot
        # 同 id 覆盖: 活文件里旧文本已被替换(与 zip 里的旧状态形成对照)
        live = json.dumps(_read(os.path.join(d, "tasks.json")), ensure_ascii=False)
        assert "导入前的老数据标记" not in live and "导入后的新数据" in live
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_partial_sections_leave_others_untouched():
    d = _dir_with_tasks({"2099-07-01": [{"id": "keep", "text": "别动我", "done": False}]})
    try:
        before = _read(os.path.join(d, "tasks.json"))
        bundle = {"kind": "full-export", "data": {
            "daily/analysis.json": {"notes": {"2099-07-01": {"concepts": ["a"]}}}}}
        transfer.import_bundle(d, bundle, now=NOW)
        assert _read(os.path.join(d, "tasks.json")) == before, "无 tasks 段就不许碰任务库"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_bad_section_skipped_with_warning():
    d = _dir_with_tasks({})
    try:
        before = _read(os.path.join(d, "tasks.json"))       # 夹具已创建 tasks.json
        bundle = {"kind": "full-export", "data": {
            "tasks.json": "我不是字典",
            "daily/analysis.json": {"notes": {"2099-07-01": {"concepts": ["a"]}}}}}
        out = transfer.import_bundle(d, bundle, now=NOW)
        assert out["ok"] is True                                # 一个坏段不拖垮整体
        assert any("tasks" in w for w in out["warnings"]), out
        assert _read(os.path.join(d, "tasks.json")) == before   # 坏段: 内容一字未动
        assert os.path.exists(os.path.join(d, "daily", "analysis.json"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- roundtrip ----------------
def test_export_import_roundtrip_into_fresh_dir():
    src = _dir_with_tasks({
        "2099-07-01": [{"id": "r1", "text": "甲", "done": True},
                       {"id": "r2", "text": "乙", "done": False}]},
        history=[{"date": "2099-07-01", "total": 2, "done": 1, "rate": 0.5}])
    dst = tempfile.mkdtemp()
    try:
        _write(os.path.join(src, "daily", "analysis.json"),
               {"notes": {"2099-07-01": {"topic": "T", "concepts": ["概念"], "tags": [], "code_langs": []}}})
        bundle = transfer.export_bundle(src, now=NOW)
        out = transfer.import_bundle(dst, bundle, now=NOW)
        assert out["ok"] is True, out
        st = _read(os.path.join(dst, "tasks.json"))
        assert len(st["days"]["2099-07-01"]) == 2
        assert st["history"][0]["rate"] == 0.5
        notes = _read(os.path.join(dst, "daily", "analysis.json"))["notes"]
        assert notes["2099-07-01"]["concepts"] == ["概念"]
        g = _read(os.path.join(dst, "daily", "graph.json"))     # 图谱在空目录也能重建出来
        assert any(n["id"] == "概念" for n in g["nodes"])
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_summary_has_expected_shape():
    d = _dir_with_tasks({})
    try:
        out = transfer.import_bundle(
            d, {"kind": "full-export", "data": {"tasks.json": {"days": {}, "history": [], "log": []}}},
            now=NOW)
        assert set(out.keys()) >= {"ok", "backup", "sections", "warnings"}, out
        assert "tasks" in out["sections"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
