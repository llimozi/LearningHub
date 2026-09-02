# -*- coding: utf-8 -*-
"""visual_regression/capture.py —— 截图核心（服务管理 + Ready 等待 + 截图）。

职责：
1. 用 create_server() 内嵌启动测试服务（端口自动 +1，不干扰用户正式服务）
2. 测试前后备份/恢复数据文件（render 有写盘副作用，禁止污染真实数据）
3. 每组合按 Ready 条件等待页面就绪后截图（支持 mask 动态区域）
4. 注入动画冻结 CSS（不修改生产文件）
"""
import asyncio
import json
import os
import shutil
import sys
import time

import config

# 允许从项目根 import build_dashboard
sys.path.insert(0, config.PROJECT_ROOT)


def backup_data_files():
    """备份会被服务写盘的数据文件到 .backup/，返回是否备份成功。"""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    saved = []
    for rel in config.DATA_FILES_TO_PROTECT:
        src = os.path.join(config.PROJECT_ROOT, rel)
        if os.path.exists(src):
            dst = os.path.join(config.BACKUP_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            saved.append(rel)
    return saved


def restore_data_files():
    """从 .backup/ 恢复数据文件（测试结束必须调用）。"""
    for rel in config.DATA_FILES_TO_PROTECT:
        bak = os.path.join(config.BACKUP_DIR, rel)
        if os.path.exists(bak):
            dst = os.path.join(config.PROJECT_ROOT, rel)
            shutil.copy2(bak, dst)
            os.remove(bak)


def set_theme(theme_name):
    """写入 settings.json 的 theme 字段（theme.current_theme 每次读文件，无需重启服务）。"""
    path = os.path.join(config.PROJECT_ROOT, "settings.json")
    with open(path, encoding="utf-8-sig") as f:
        st = json.load(f)
    st["theme"] = theme_name
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def start_server():
    """内嵌启动测试服务。返回 (server, port)。端口占用自动 +1，不干扰用户正式服务。"""
    import build_dashboard
    srv, port = build_dashboard.create_server(config.PORT0)
    if not srv:
        return None, None
    return srv, port


async def _wait_ready(page, page_name, timeout_ms=config.FETCH_TIMEOUT):
    """按 READY_CONDITIONS 等待页面就绪。"""
    conds = config.READY_CONDITIONS[page_name]
    t0 = time.time()
    for kind, arg in conds:
        if kind == "selector":
            await page.wait_for_selector(arg, timeout=timeout_ms, state="attached")
        elif kind == "networkidle":
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        if time.time() - t0 > timeout_ms / 1000 + 5:
            raise TimeoutError("Ready 等待超时: %s" % page_name)


async def capture_combo(browser, page_name, theme, viewport, out_path,
                        viewport_size, server_port):
    """截图单个组合。返回截图 bytes。"""
    url = "http://%s:%d%s" % (config.HOST, server_port,
                              config.PAGE_URLS[page_name])
    # 每次新建 context：隔离 localStorage，保证同一项目状态 → 同一截图
    context = await browser.new_context(
        viewport={"width": viewport_size[0], "height": viewport_size[1]},
        device_scale_factor=config.DEVICE_SCALE_FACTOR,
    )
    try:
        # 动画冻结注入（不修改生产 CSS）
        await context.add_init_script(config.ANIMATION_FREEZE_CSS)
        page = await context.new_page()
        # 监听网络请求失败（诊断用）
        page.on("requestfailed", lambda r: print(
            "  [warn] request failed:", r.url, r.failure))
        await page.goto(url, wait_until="domcontentloaded", timeout=config.FETCH_TIMEOUT)
        await _wait_ready(page, page_name)
        await page.wait_for_timeout(config.POST_READY_DELAY_MS)

        # mask 动态区域（clock 等）
        mask_locs = []
        for sel in config.MASK_SELECTORS.get(page_name, []):
            loc = page.locator(sel).first
            if await loc.count() > 0:
                mask_locs.append(loc)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        await page.screenshot(path=out_path, mask=mask_locs)
        with open(out_path, "rb") as f:
            data = f.read()
        return data
    finally:
        await context.close()


async def capture_all(round_no, server_port):
    """截取全部组合（一轮）。返回 {combo_name: bytes}。"""
    from playwright.async_api import async_playwright
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for page_name in config.PAGES:
                for theme in config.THEMES:
                    set_theme(theme)
                    for vp_name, vp_size in config.VIEWPORTS.items():
                        name = config.combo_name(page_name, theme, vp_name)
                        out = os.path.join(
                            config.CURRENT_DIR, page_name,
                            "%s__r%d.png" % (name, round_no))
                        try:
                            await capture_combo(
                                browser, page_name, theme, vp_name, out, vp_size,
                                server_port)
                            results[name] = out
                            print("  [ok] %s (r%d)" % (name, round_no))
                        except Exception as e:
                            print("  [FAIL] %s (r%d): %s" % (name, round_no, e))
        finally:
            await browser.close()
    return results


def run_capture(round_no, server_port):
    """同步入口：截取一轮全部组合。"""
    return asyncio.run(capture_all(round_no, server_port))
