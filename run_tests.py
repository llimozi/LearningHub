# -*- coding: utf-8 -*-
r"""run_tests.py —— 一键测试入口 (v1.4 · 纯标准库)

用法: python run_tests.py            # 跑全部 *_test.py + build_dashboard --selftest
      产物: 控制台逐套结果 + tests_output\test_report_YYYYMMDD_HHMMSS.md 报告
      退出码: 全绿 0 / 有失败 1

设计:
  发现器只收「*_test.py」且排除自身; 套件计划把 --selftest 三场景回归排在首位。
  每套用子进程独立执行(零依赖 runner 口径, 不要求装 pytest), 解析其约定输出行:
    RUNNER: ALL GREEN (N tests)  → N 用例全过
    RUNNER: M FAILED             → 共 (PASS行数+M) 例, 其中 M 失败
    SELFTEST: PASS/FAIL          → 记 1 例(三场景合并口径)
"""
import os
import re
import sys
import time
import datetime

import paths

_TEST_RE = re.compile(r"^.+_test\.py$")

# 数据防护栏: 受 git 跟踪、且测试可能因 render()/selftest 副作用写入的运行时文件。
# 套件结束后字节级比对, 有变化即原子恢复(消除代码 commit 与数据 rollover 混杂的 Git 噪音)。
# 依据: 2026-08-31 治理整改（refactor_phase2/44 系列）; 与视觉回归框架同口径。
_GUARD_FILES = [
    "tasks.json", "STATUS.json", "settings.json",
    os.path.join("daily", "analysis.json"),
    os.path.join("daily", "graph.json"),
    os.path.join("daily", "knowledge.json"),
    "dashboard.html", "editor.html",
]


def _snapshot_guard(base):
    snap = {}
    for rel in _GUARD_FILES:
        try:
            with open(os.path.join(base, rel), "rb") as f:
                snap[rel] = f.read()
        except OSError:
            snap[rel] = None
    return snap


def _restore_guard(base, snap):
    """字节级比对; 变化文件以 .tmp + os.replace 原子恢复。返回被恢复的相对路径列表。"""
    reverted = []
    for rel, data in snap.items():
        p = os.path.join(base, rel)
        try:
            with open(p, "rb") as f:
                cur = f.read()
        except OSError:
            cur = None
        if cur == data:
            continue
        try:
            if data is None:
                os.remove(p)
            else:
                tmp = p + ".tmp_guard"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, p)
            reverted.append(rel)
        except OSError:
            reverted.append(rel + " (恢复失败)")
    return reverted


def discover(directory):
    """按文件名发现测试套件: 只收 *_test.py, 排除本脚本"""
    out = []
    for fn in sorted(os.listdir(directory)):
        if _TEST_RE.match(fn) and fn != "run_tests.py":
            out.append(os.path.join(directory, fn))
    return out


def plan_suite(directory, files=None, include_selftest=True):
    """编排执行计划: [(标签, [argv])]。--selftest 三场景回归排最前。"""
    files = discover(directory) if files is None else files
    plan = []
    if include_selftest:
        bd = os.path.join(directory, "build_dashboard.py")
        if os.path.exists(bd):
            plan.append(("build_dashboard --selftest",
                         [sys.executable, bd, "--selftest"]))
    for p in files:
        plan.append((os.path.basename(p), [sys.executable, p]))
    return plan


def summarize(stdout):
    """解析零依赖 runner 约定输出 → (总用例数, 失败数)"""
    if "SELFTEST:" in stdout:
        return (1, 0 if "SELFTEST: PASS" in stdout else 1)
    m = re.search(r"RUNNER:\s*ALL GREEN \((\d+) tests\)", stdout)
    if m:
        return int(m.group(1)), 0
    m = re.search(r"RUNNER:\s*(\d+) FAILED", stdout)
    if m:
        failed = int(m.group(1))
        total = len(re.findall(r"^PASS ", stdout, re.M)) + failed
        return total, failed
    return 0, 1                                              # 无约定输出视为异常失败


def run_one(argv):
    """子进程跑一个套件; 返回 {name,ok,total,failed,dur,out}"""
    name = os.path.basename(argv[1]) + (" " + argv[-1] if "--selftest" in argv else "")
    t0 = time.time()
    r = subprocess_run(argv)
    dur = round(time.time() - t0, 2)
    total, failed = summarize(r.stdout or "")
    ok = (r.returncode == 0)
    if failed:
        ok = False
    elif total == 0 and not ok:
        total, failed = 1, 1
    return {"name": name.strip(), "ok": ok, "total": total,
            "failed": failed, "dur": dur, "out": (r.stdout or "")[-2000:]}


def subprocess_run(argv):
    import subprocess
    return subprocess.run(argv, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def render_md(results, dur_s):
    """Markdown 报告: 汇总表 + 失败明细提示"""
    total = sum(r["total"] for r in results)
    failed = sum(r["failed"] for r in results)
    lines = ["# 自动化测试报告", "",
             "> 生成于 %s · 总耗时 %.1fs" % (
                 datetime.datetime.now().isoformat(timespec="seconds"), dur_s),
             "",
             "| 测试套件 | 用例 | 失败 | 耗时s | 结果 |",
             "|---|---|---|---|---|"]
    for r in results:
        verdict = "✅ 通过" if r["ok"] else ("❌ 失败 %d" % r["failed"])
        lines.append("| %s | %d | %d | %.2f | %s |"
                     % (r["name"], r["total"], r["failed"], r["dur"], verdict))
    lines.append("")
    if failed:
        lines.append("**未通过 %d 例**——请逐套排查后重跑。" % failed)
    else:
        lines.append("**全部通过** 🎉")
    return "\n".join(lines)


def main():
    base = paths.app_base()
    plan = plan_suite(base)
    if not plan:
        print("[ERR] 未发现任何 *_test.py")
        return 1
    print("=== LearningHub 一键测试 · 共 %d 套 ===" % len(plan))
    snap = _snapshot_guard(base)
    reverted = []
    results, t0 = [], time.time()
    try:
        for label, argv in plan:
            res = run_one(argv)
            res["name"] = label
            results.append(res)
            mark = "✅" if res["ok"] else "❌"
            print("%s %-32s 用例 %3d · 失败 %d · %.2fs"
                  % (mark, res["name"], res["total"], res["failed"], res["dur"]))
    finally:
        reverted = _restore_guard(base, snap)
    if reverted:
        print("--- 数据防护栏: 已恢复 %d 个测试副作用文件: %s"
              % (len(reverted), ", ".join(reverted)))
    dur = time.time() - t0
    md = render_md(results, dur)
    if reverted:
        md += ("\n\n> 数据防护栏: %d 个运行时文件被测试写入, 已原子恢复: %s"
               % (len(reverted), ", ".join(reverted)))
    rdir = os.path.join(base, "tests_output")
    os.makedirs(rdir, exist_ok=True)
    rp = os.path.join(rdir, "test_report_" +
                      datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".md")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    failed = sum(r["failed"] for r in results)
    print("---")
    print("报告: %s" % rp)
    print("结果: %d 套 / %d 例 / 失败 %d" %
          (len(results), sum(r['total'] for r in results), failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
