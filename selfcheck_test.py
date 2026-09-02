# -*- coding: utf-8 -*-
"""selfcheck_test.py —— run_tests.py 与 health_check.py 单元测试 (v1.4)
跑法A: pytest selfcheck_test.py      跑法B: python selfcheck_test.py
覆盖: 测试发现器(只收 *_test.py 且排除自身) / 套件计划含 --selftest /
      输出解析(全绿与带失败两种口径) / 单用例子进程执行集成 /
      报告渲染含汇总 / 健康检查四项(核心文件·JSON完整性·端口·磁盘) /
      硬失败决定退出码。全部临时目录+注入探测函数。
"""
import json
import os
import shutil
import sys
import tempfile
import types

import run_tests
import health_check


# ---------------- run_tests ----------------
def _mk_suite_dir():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "a_test.py"), "w", encoding="utf-8").close()
    open(os.path.join(d, "b_test.py"), "w", encoding="utf-8").close()
    open(os.path.join(d, "run_tests.py"), "w", encoding="utf-8").close()   # 必须被排除
    open(os.path.join(d, "not_a_suite.txt"), "w", encoding="utf-8").close()
    return d


def test_discover_only_test_files_excluding_self():
    d = _mk_suite_dir()
    try:
        names = [os.path.basename(p) for p in run_tests.discover(d)]
        assert names == ["a_test.py", "b_test.py"], names
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_plan_suite_prepends_selftest_when_available():
    d = _mk_suite_dir()
    open(os.path.join(d, "build_dashboard.py"), "w", encoding="utf-8").close()
    try:
        plan = run_tests.plan_suite(d)
        assert plan[0][0] == "build_dashboard --selftest", plan[0]
        assert len(plan) == 3, plan                              # selftest + 两套测试
        assert all(argv[-1].endswith(".py") or "--selftest" in argv
                   for _l, argv in plan)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_summarize_all_green_and_failed_variants():
    assert run_tests.summarize("PASS a\nPASS b\nRUNNER: ALL GREEN (2 tests)") == (2, 0)
    out = "PASS a\nFAIL b\nFAIL c\nRUNNER: 2 FAILED"
    assert run_tests.summarize(out) == (3, 2), (3, 2)
    assert run_tests.summarize("SELFTEST: PASS") == (1, 0)
    assert run_tests.summarize("SELFTEST: FAIL") == (1, 1)


def test_run_one_executes_real_script(tmpdir=None):
    d = tempfile.mkdtemp()
    try:
        good = os.path.join(d, "good.py")
        with open(good, "w", encoding="utf-8") as f:
            f.write('print("PASS x\\nRUNNER: ALL GREEN (1 tests)")\n')
        res = run_tests.run_one([sys.executable, good])
        assert res["ok"] is True and res["total"] == 1 and res["failed"] == 0, res
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_render_report_has_summary_table():
    results = [
        {"name": "a_test.py", "ok": True, "total": 12, "failed": 0, "dur": 1.2},
        {"name": "b_test.py", "ok": False, "total": 5, "failed": 2, "dur": 0.4},
    ]
    md = run_tests.render_md(results, 1.6)
    assert "| 测试套件 | 用例 | 失败 | 耗时s | 结果 |" in md
    assert "a_test.py" in md and "b_test.py" in md
    assert "**未通过 2 例**" in md or "失败 2" in md, md          # 失败明细可见


# ---------------- health_check ----------------
def test_core_files_ok_and_missing_listed():
    d = tempfile.mkdtemp()
    full = tempfile.mkdtemp()
    try:
        for n in ("tasks.json", "settings.json", "STATUS.json"):
            open(os.path.join(full, n), "w", encoding="utf-8").write("{}")
        os.makedirs(os.path.join(full, "daily"))
        r_ok = health_check.check_core_files(full)
        assert r_ok["level"] == "ok", r_ok
        r_bad = health_check.check_core_files(d)
        assert r_bad["level"] == "fail" and "tasks.json" in r_bad["detail"], r_bad
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(full, ignore_errors=True)


def test_json_integrity_flags_broken_file():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "tasks.json"), "w", encoding="utf-8") as f:
            f.write("{半截")
        r = health_check.check_json_integrity(d)
        assert any(x["level"] == "fail" and "tasks.json" in x["name"] for x in r), r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_disk_space_with_injected_usage():
    MB = 1024 * 1024
    d = tempfile.mkdtemp()
    try:
        big = types.SimpleNamespace(free=900 * MB)
        ok_r = health_check.check_disk(d, min_free_mb=500, usage=lambda p: big)
        assert ok_r["level"] == "ok", ok_r
        small = types.SimpleNamespace(free=120 * MB)
        bad_r = health_check.check_disk(d, min_free_mb=500, usage=lambda p: small)
        assert bad_r["level"] == "fail" and "500" in bad_r["detail"], bad_r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_port_probe_free_vs_occupied():
    r_free = health_check.check_port(57999, connector=lambda p: False)
    assert r_free["level"] == "info" and "空闲" in r_free["detail"], r_free
    r_busy = health_check.check_port(57998, connector=lambda p: True)
    assert r_busy["level"] == "info" and "运行中" in r_busy["detail"], r_busy


def test_overall_exit_code_driven_by_hard_fails_only():
    ok_res = [{"name": "a", "level": "ok"}, {"name": "b", "level": "warn"}]
    bad_res = ok_res + [{"name": "c", "level": "fail"}]
    assert health_check.exit_code_for(ok_res) == 0              # warn 不影响退出码
    assert health_check.exit_code_for(bad_res) == 1             # 硬失败才置 1


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
