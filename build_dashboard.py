# -*- coding: utf-8 -*-
"""学习仪表盘 v0.3 —— 智能规划引擎（planner.py 提供统计/疲劳/优先级/预测）
上一版: v0.2 勾选写回 + rollover 三规则
用法:
  python build_dashboard.py              # 交互模式: 本地服务(仅127.0.0.1)并自动开浏览器
  python build_dashboard.py --no-open    # 静态快照导出 dashboard.html(只读, 不能勾选)
  python build_dashboard.py --no-browser # 启服务但不开浏览器(冒烟测试用)
  python build_dashboard.py --selftest   # 内置三场景断言, 验证顺延规则, 不碰真实数据
只用标准库, 零第三方依赖。
"""
import os, sys, webbrowser
import logging
from http.server import ThreadingHTTPServer
import planner
import heatmap
import analyzer
import graph
import recommender
import settings
import backup
import transfer
import forgetting
import reportio
import adaptive
import mastery
import weakspot
import theme
import search
import paths
import firstrun
import helpcenter
import analytics
import duration
import nl_capture

# Phase 2.1: 常量与工具函数迁移至 _app/（config.py / utils.py），此处 re-export 保持兼容
from _app.config import *
from _app.utils import *
# Phase 2.2: 数据访问/IO 迁移至 _app/data.py
from _app.data import *
# Phase 2.2-2.3 提前迁移: 业务/API 拆分组（_expire_fatigue_meta / daily_focus）
from _app.services import *
from _app.api import *
# Phase 2.5: HTTP 服务层(Handler) 迁移至 _app/server.py
from _app.server import *
# Phase 2.6: 渲染层(render) 迁移至 _app/renderer.py
from _app.renderer import *

# v1.4 打包态关键改造说明: 源码态=脚本目录; PyInstaller 单文件态=exe 所在目录。
# BASE 等常量已迁移至 _app/config.py（Phase 2.1），此处 import 自 _app.config。


def selftest():
    # 场景A 整批顺延
    st = {"days": {"2099-01-01": [
        {"id": "a1", "text": "x1", "done": False, "carried": False, "src_date": "2099-01-01"},
        {"id": "a2", "text": "x2", "done": False, "carried": False, "src_date": "2099-01-01"}]}, "log": []}
    r = rollover(st, "2099-01-01", persist=False)
    ok_a = len(st["days"]["2099-01-02"]) == 2 and all(t["carried"] for t in st["days"]["2099-01-02"]) and not st["days"]["2099-01-01"] and "整批" in r
    # 场景B 部分顺延
    st = {"days": {"2099-01-01": [
        {"id": "b1", "text": "y1", "done": True, "carried": False, "src_date": "2099-01-01"},
        {"id": "b2", "text": "y2", "done": False, "carried": False, "src_date": "2099-01-01"},
        {"id": "b3", "text": "y3", "done": False, "carried": False, "src_date": "2099-01-01"}]}, "log": []}
    r = rollover(st, "2099-01-01", persist=False)
    ok_b = [t["id"] for t in st["days"]["2099-01-02"]] == ["b2", "b3"] and all(t["carried"] for t in st["days"]["2099-01-02"]) and [t["id"] for t in st["days"]["2099-01-01"]] == ["b1"]
    # 场景C 全部完成
    st = {"days": {"2099-01-01": [
        {"id": "c1", "text": "z1", "done": True, "carried": False, "src_date": "2099-01-01"}]}, "log": []}
    r = rollover(st, "2099-01-01", persist=False)
    ok_c = "无遗留" in r and "2099-01-02" not in st["days"]
    print("TEST-A batch-defer:", "PASS" if ok_a else "FAIL")
    print("TEST-B partial-defer:", "PASS" if ok_b else "FAIL")
    print("TEST-C all-done:", "PASS" if ok_c else "FAIL")
    print("SELFTEST:", "PASS" if (ok_a and ok_b and ok_c) else "FAIL")

def create_server(port0=PORT0):
    """在 127.0.0.1 起服务, 端口占用自动 +1 试 6 个; 返回 (server|None, 实际端口)。
    v1.0 拆分: resident.py 复用本函数把服务嵌进常驻进程。"""
    for off in range(6):
        port = port0 + off
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler), port
        except OSError:
            continue
    return None, port0

def _setup_logging():
    """配置全局日志: 错误级别写入 app.log, 避免静默丢失。"""
    log_path = os.path.join(BASE, "app.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.ERROR,
        encoding="utf-8",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    # 全局日志配置: 错误写入 app.log, 不再静默丢失
    _setup_logging()
    if "--selftest" in sys.argv:
        selftest(); return
    interactive = "--no-open" not in sys.argv
    st = load_tasks()
    daily = read_file(os.path.join("daily", TODAY + ".md"))
    init_today_from_daily(st, daily)
    n_pri = planner.normalize_priorities(st)
    if n_pri:
        save_tasks(st)
    ups = auto_catchup(st)
    if ups:
        print("[catchup]", " | ".join(ups))
    if interactive:
        touch_last_open()                           # v1.0: 记录打开时刻(连续未打开提醒依据)
        try:                                        # v1.4: 首次运行必须最先初始化结构
            fw = firstrun.ensure_workspace(BASE)
            if fw["created"]:
                print("[firstrun]", "已创建:", ", ".join(fw["created"]))
        except Exception as _fe:
            print("[firstrun] skipped:", str(_fe)[:80])
            logging.error("Boundary error in main.firstrun: %s", _fe, exc_info=True)
        try:                                        # v1.1: 到点自动备份(24h 窗口)
            bkp = backup.maybe_backup(BASE)
            if bkp:
                print("[backup]", os.path.basename(bkp))
        except Exception as _be:
            print("[backup] skipped:", str(_be)[:80])
            logging.error("Boundary error in main.backup: %s", _be, exc_info=True)
        try:                                        # v1.1: 当周/当月报告缺才生成
            reps = reportio.ensure_reports(BASE)
            if reps["created"]:
                print("[reports]", ", ".join(reps["created"]))
        except Exception as _re:
            print("[reports] skipped:", str(_re)[:80])
            logging.error("Boundary error in main.reports: %s", _re, exc_info=True)
        try:                                        # v1.2: 周日自动薄弱点分析与下周排练
            ws = weakspot.weekly_analysis(BASE)
            if ws.get("ran") and ws.get("report"):
                print("[weakspot]", ws["report"],
                      ("插入 %d 条" % len(ws["added"])) if ws["added"] else "无薄弱点")
        except Exception as _we:
            print("[weakspot] skipped:", str(_we)[:80])
            logging.error("Boundary error in main.weakspot: %s", _we, exc_info=True)
        try:                                        # v1.4: 首次运行初始化缺失结构
            fw = firstrun.ensure_workspace(BASE)
            if fw["created"]:
                print("[firstrun]", "已创建:", ", ".join(fw["created"]))
        except Exception as _fe:
            print("[firstrun] skipped:", str(_fe)[:80])
            logging.error("Boundary error in main.firstrun_retry: %s", _fe,
                          exc_info=True)
        try:                                        # v1.3: 启动即构建全文索引(有缓存则复用)
            idx = search.build_index(BASE)
            print("[search]", "docs =", idx["_stats"]["docs"])
        except Exception as _se:
            print("[search] skipped:", str(_se)[:80])
            logging.error("Boundary error in main.search_index: %s", _se,
                          exc_info=True)
    if not interactive:
        out = os.path.join(BASE, "dashboard.html")
        with open(out, "w", encoding="utf-8-sig") as f:
            f.write(render(False))
        print("[OK] static snapshot -> " + out)
        return
    srv, port = create_server(PORT0)
    if not srv:
        print("[ERR] ports %d-%d all busy" % (PORT0, PORT0 + 5)); sys.exit(1)
    url = "http://127.0.0.1:%d/" % port
    print("[OK] serving " + url + "  (Ctrl+C or close window to stop)")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bye]")

if __name__ == "__main__":
    main()
