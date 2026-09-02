# -*- coding: utf-8 -*-
"""visual_regression/run_visual_tests.py —— 视觉回归测试主入口。

用法（在 visual_regression/ 目录下，用 anaconda3 python 运行）：
    python run_visual_tests.py                     # 与 baseline 对比（正常回归）
    python run_visual_tests.py --update-baseline   # 显式更新 baseline（先 3 次稳定性验证）
    python run_visual_tests.py --stability-only    # 仅 3 次稳定性验证（不更新/不比 baseline）
    python run_visual_tests.py --combo dashboard dark desktop   # 只跑指定组合

流程：
1. 记录当前 git commit
2. 备份数据文件 → 内嵌启动测试服务（端口自动 +1，不干扰正式服务）
3. 每组合连续 3 次截图（Ready 条件 + mask 动态区 + 动画冻结）
4. 3 次互比稳定性分析（max_ratio ≤ 5% 才视为稳定）
5. 正常模式：与 baseline 像素 diff → PASS/FAIL
   更新模式：稳定才写入 baseline + 更新 baseline_info.md
6. 关闭服务 → 恢复数据文件
"""
import datetime
import os
import subprocess
import sys
import threading
import time

import config
import capture
import compare

# ---------------- 服务线程 ----------------
_server = None
_server_port = None
_server_err = []


def _serve():
    global _server, _server_port, _server_err
    srv, port = capture.start_server()
    if not srv:
        _server_err.append("端口 %d-%d 全部被占，无法启动测试服务" % (
            config.PORT0, config.PORT0 + 5))
        return
    _server_port = port
    _server = srv
    try:
        srv.serve_forever()
    except Exception as e:
        _server_err.append("serve error: %s" % e)


def _wait_port(port, timeout=config.SERVER_TIMEOUT):
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((config.HOST, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def start_test_server():
    """启动测试服务（后台线程）。返回实际端口。"""
    global _server, _server_port, _server_err
    _server = None
    _server_port = None
    _server_err = []
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    # 等待端口就绪（create_server 可能 +1 偏移）
    for _ in range(config.SERVER_TIMEOUT * 10):
        if _server_port is not None:
            break
        if _server_err:
            raise RuntimeError(_server_err[0])
        time.sleep(0.1)
    if _server_port is None:
        raise RuntimeError("测试服务启动超时")
    if not _wait_port(_server_port):
        raise RuntimeError("端口 %d 无法连接" % _server_port)
    return _server_port


def stop_test_server():
    global _server
    if _server:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None


# ---------------- git 工具 ----------------
def git(cmd):
    r = subprocess.run(
        ["git", "-C", config.PROJECT_ROOT] + cmd,
        capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()


def current_commit():
    return git(["rev-parse", "--short", "HEAD"])


# ---------------- 稳定性验证 ----------------
def stability_verify(round_files):
    """对同一组合 3 轮截图做互比。返回 (stable, max_ratio, details)"""
    if len(round_files) < 2:
        return False, 1.0, {}
    res = compare.compare_rounds(round_files)
    return res["stable"], res["max_ratio"], res["pairs"]


# ---------------- 截图一轮 ----------------
def capture_one_round(round_no, port, only_combo=None):
    """截取一轮。only_combo=(page, theme, viewport) 时只截该组合。"""
    import asyncio
    from playwright.async_api import async_playwright

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for page_name in config.PAGES:
                    for theme in config.THEMES:
                        for vp_name in config.VIEWPORTS:
                            if only_combo and (page_name, theme, vp_name) != only_combo:
                                continue
                            capture.set_theme(theme)
                            name = config.combo_name(page_name, theme, vp_name)
                            out = os.path.join(
                                config.CURRENT_DIR, page_name,
                                "%s__r%d.png" % (name, round_no))
                            try:
                                await capture.capture_combo(
                                    browser, page_name, theme, vp_name, out,
                                    config.VIEWPORTS[vp_name], port)
                                print("  [ok] %s (r%d)" % (name, round_no))
                            except Exception as e:
                                print("  [FAIL] %s (r%d): %s" % (name, round_no, e))
            finally:
                await browser.close()

    asyncio.run(_run())


# ---------------- 主流程 ----------------
def main():
    args = sys.argv[1:]
    mode = "compare"
    only_combo = None
    if "--update-baseline" in args:
        mode = "update"
    elif "--stability-only" in args:
        mode = "stability"
    if "--combo" in args:
        i = args.index("--combo")
        only_combo = tuple(args[i + 1:i + 4])

    commit = current_commit()
    print("=" * 62)
    print("视觉回归测试   commit=%s   模式=%s" % (commit, mode))
    if only_combo:
        print("限定组合:", only_combo)
    print("=" * 62)

    # 1. 数据保护 + 启动服务
    saved = capture.backup_data_files()
    print("[1/6] 数据文件已备份 (%d 个): %s" % (len(saved), ", ".join(saved[:3]) + ("..." if len(saved) > 3 else "")))
    port = start_test_server()
    print("[2/6] 测试服务启动 127.0.0.1:%d（独立端口，不干扰正式服务）" % port)

    try:
        # 2. 每组合连续 3 次截图
        print("[3/6] 连续 %d 次截图（每组合）..." % config.STABILITY_ROUNDS)
        for r in range(1, config.STABILITY_ROUNDS + 1):
            capture_one_round(r, port, only_combo)

        # 3. 稳定性分析
        print("[4/6] 稳定性验证（3 次互比）...")
        stable_results = {}
        for page_name in config.PAGES:
            for theme in config.THEMES:
                for vp_name in config.VIEWPORTS:
                    if only_combo and (page_name, theme, vp_name) != only_combo:
                        continue
                    name = config.combo_name(page_name, theme, vp_name)
                    rounds = [os.path.join(config.CURRENT_DIR, page_name,
                                           "%s__r%d.png" % (name, r))
                              for r in range(1, config.STABILITY_ROUNDS + 1)]
                    rounds = [p for p in rounds if os.path.exists(p)]
                    if len(rounds) < 3:
                        print("  [SKIP] %s: 截图不足 3 张" % name)
                        continue
                    stable, max_ratio, pairs = stability_verify(rounds)
                    stable_results[name] = (stable, max_ratio)
                    flag = "STABLE" if stable else "UNSTABLE"
                    print("  [%s] %-38s max_ratio=%.3f%%" % (
                        flag, name, max_ratio * 100))
                    for pair, res in pairs.items():
                        print("         %s: changed=%d/%d (%.3f%%)" % (
                            pair, res["changed"], res["total"], res["ratio"] * 100))

        unstable = {k: v for k, v in stable_results.items() if not v[0]}
        if unstable:
            print("[5/6] !! %d 个组合不稳定，无法建立/比对 baseline: %s" % (
                len(unstable), ", ".join(unstable.keys())))
            print("    排查方向: fetch / animation / 时间 / 随机 / font / cache / GPU / DSF")
            print("    未修改任何 baseline（保持既有契约）。")
            return 1

        # 4. baseline 对比或更新
        if mode == "compare":
            print("[5/6] 与 baseline 像素 diff ...")
            if not os.path.exists(config.BASELINE_DIR):
                print("  !! baseline 不存在，请先运行: python run_visual_tests.py --update-baseline")
                return 1
            fails = []
            total = 0
            for name, (stable, _) in stable_results.items():
                page_name, theme, vp_name = name.split("__")
                bl = config.shot_path(config.BASELINE_DIR, page_name, theme, vp_name)
                cur = os.path.join(config.CURRENT_DIR, page_name, "%s__r1.png" % name)
                if not os.path.exists(bl):
                    fails.append((name, "缺 baseline"))
                    continue
                diff_out = os.path.join(config.DIFF_DIR, page_name, name + ".png")
                res = compare.compare_images(bl, cur, diff_out)
                total += 1
                ok = res["ratio"] <= config.DIFF_RATIO_THRESHOLD
                status = "PASS" if ok else "FAIL"
                print("  [%s] %-38s changed=%d/%d (%.3f%% <= %.2f%%)" % (
                    status, name, res["changed"], res["total"],
                    res["ratio"] * 100, config.DIFF_RATIO_THRESHOLD * 100))
                if not ok:
                    fails.append((name, "ratio=%.3f%%" % (res["ratio"] * 100)))
            print("  结果: %d/%d 通过" % (total - len(fails), total))
            if fails:
                print("  失败组合:", "; ".join("%s(%s)" % f for f in fails))
                return 1
            print("[6/6] 视觉回归全部通过 ✔")

        elif mode == "update":
            print("[5/6] 更新 baseline（仅稳定组合）...")
            print("  !! 警告: 将覆盖既有 baseline，请确认这是预期变更")
            print("  !! 建议: 先跑 run_tests.py 业务测试确认功能无回归")
            n = 0
            for name, (stable, _) in stable_results.items():
                if not stable:
                    continue
                page_name, theme, vp_name = name.split("__")
                bl = config.shot_path(config.BASELINE_DIR, page_name, theme, vp_name)
                cur = os.path.join(config.CURRENT_DIR, page_name, "%s__r1.png" % name)
                os.makedirs(os.path.dirname(bl), exist_ok=True)
                # 用 r1 作为 baseline（稳定性已验证 3 次一致）
                import shutil
                shutil.copy2(cur, bl)
                n += 1
            # 记录 commit 与时间
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(config.COMMIT_RECORD_FILE, "w", encoding="utf-8") as f:
                f.write("# Visual Regression Baseline v1\n\n")
                f.write("- 更新时间: %s\n" % now)
                f.write("- 更新时 commit: %s\n" % commit)
                f.write("- 更新模式: --update-baseline（显式）\n")
                f.write("- 覆盖组合数: %d\n" % n)
                f.write("- 说明: 3 次截图稳定性验证通过后，取 r1 作为 baseline\n")
            print("  已更新 %d 个组合 baseline，commit=%s" % (n, commit))
            print("  git diff 提示: 请检查 baseline 变化是否符合预期")

        elif mode == "stability":
            print("[5/6] 仅稳定性验证完成（未更新 baseline）")
            all_stable = all(v[0] for v in stable_results.values())
            print("[6/6] %s" % ("全部组合稳定 ✔" if all_stable else "存在不稳定组合 ✘"))
            if not all_stable:
                return 1

    finally:
        # 5. 关闭服务 + 恢复数据
        stop_test_server()
        capture.restore_data_files()
        print("服务已关闭，数据文件已恢复（真实数据未污染）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
