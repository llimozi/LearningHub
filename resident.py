# -*- coding: utf-8 -*-
"""resident.py —— 桌面常驻壳 (v1.0 · 纯标准库, 双击/开机自启入口)

线程全景(三条线, 只靠两样东西过河: queue 事件 / HTTP 接口):
  主线程    Tk 主循环: 控制窗 + 快速记录对话框 + toast 通知 + 托盘菜单
  服务线程  build_dashboard.create_server() 的本地服务(仪表盘/编辑器/全部接口)
  托盘线程  tray.TrayIcon: 图标 + Ctrl+Shift+L 热键, 事件经队列投回主线程

启动流程:
  单实例检测(已有实例在跑 -> 直接开它的页面并退出) -> 抓 STATUS.last_open_ts 旧值快照 ->
  touch_last_open 覆盖为新值 -> 起服务线程 -> 建 Tk 控制窗 -> 挂托盘 ->
  首次提醒检查 -> 之后每 60 秒一轮(root.after), 每 100 毫秒消费托盘队列。

退出流程(唯一入口 quit_app): 停托盘(摘图标+注销热键) -> 停服务(shutdown) -> 销毁 Tk。
控制窗点关闭 = 缩到托盘不退出; 真退出只认托盘右键菜单的「退出」。

CLI:
  resident.py               常驻启动(安静, 不自动开浏览器)
  resident.py --open        启动并立即打开仪表盘页面
  resident.py --smoke-exit  冒烟: 全组件真实起一遍, 5 秒后自退(验证编排与退出链路)

已知限制(v1.0 如实记录): 进程跨零点后 build_dashboard.TODAY 等当日常量不刷新,
日切顺延要重启应用才生效——桌面场景每晚关机自然规避, v1.1 备份机制上线后再评估。
"""
import os
import sys
import queue
import threading
import logging
import webbrowser
import urllib.request
import urllib.error
import tkinter as tk

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:                    # 从别的工作目录拉起时也能找到同目录模块
    sys.path.insert(0, BASE)

import build_dashboard as bd
import planner
import reminders as rem_mod
import tray
import paths

# v1.4 打包态: BASE 必须切到 exe 所在目录(数据与用户可见处同侧), 详见 paths.py
BASE = paths.app_base()

FONT = ("Microsoft YaHei", 9)
FONT_B = ("Microsoft YaHei", 9, "bold")
C_BG = "#1e1e2e"                            # 与仪表盘同套暗色主题
C_CARD = "#2a2a3c"
C_ACCENT = "#89b4fa"
C_TEXT = "#e0e0e0"
C_DIM = "#9399b2"


def _setup_logging():
    """配置全局日志: 错误级别写入 app.log, 避免静默丢失。"""
    log_path = os.path.join(BASE, "app.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.ERROR,
        encoding="utf-8",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ---------------- 单实例探测 ----------------
def find_running_server(port0=None, tries=6, timeout=0.5):
    """逐个试端口段, 已有本应用实例则返回其根 URL, 否则 None"""
    port0 = port0 or bd.PORT0
    for off in range(tries):
        probe = "http://127.0.0.1:%d/api/stats" % (port0 + off)
        try:
            with urllib.request.urlopen(probe, timeout=timeout):
                return probe.rsplit("/api/", 1)[0] + "/"
        except (OSError, urllib.error.URLError):
            continue                        # 连不上=这个口没实例, 试下一个
    return None


class ResidentApp(object):
    """常驻壳主体: 持有 Tk 根窗口、服务句柄、托盘、提醒调度"""

    def __init__(self, root, srv, url, preopen_snapshot=None):
        self.root = root
        self._srv = srv
        self.url = url
        self._preopen = preopen_snapshot     # 本次打开前最后活跃时刻(回归提醒依据)
        self._events = queue.Queue()         # 托盘线程 -> 主线程 的唯一通道
        self._tray = None
        self._quitting = False
        self._toasts = []
        self._task_vars = {}                 # 快速记录对话框的 BooleanVar
        self._quick = None                   # 快速记录 Toplevel 引用
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        # 托盘接线(独立线程, 起完立即返回)
        self._tray = tray.TrayIcon("学习仪表盘 · 左键唤起 · 右键菜单", self._events).start()
        self._poll_queue()                   # 100ms 一轮
        self.root.after(1200, self._tick_reminders)      # 首轮提醒(给服务留半秒热身)
        self.root.after(500, self._refresh_tray_status)  # 刷新托盘/热键状态行

    # ---------------- 控制窗 UI ----------------
    def _build_ui(self):
        r = self.root
        r.title("学习仪表盘 · 控制台 v1.0")
        r.configure(bg=C_BG)
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry("360x430+%d+%d" % (sw - 390, max(40, sh - 500)))

        head = tk.Label(r, text="📊 学习仪表盘", bg=C_BG, fg="#cdd6f4",
                        font=("Microsoft YaHei", 15, "bold"))
        head.pack(pady=(14, 0))
        self._url_label = tk.Label(r, text="服务启动中…", bg=C_BG, fg=C_DIM, font=FONT)
        self._url_label.pack()
        self._today_label = tk.Label(r, text="", bg=C_BG, fg=C_TEXT, font=FONT,
                                     wraplength=320, justify="center")
        self._today_label.pack(pady=2)
        self._refresh_today()

        box = tk.Frame(r, bg=C_CARD, padx=12, pady=10)
        box.pack(fill="x", padx=14, pady=10)
        def btn(text, cmd, accent=False, row=0, col=0):
            b = tk.Button(box, text=text, command=cmd, font=FONT_B, relief="flat",
                          cursor="hand2", padx=10, pady=5,
                          bg=C_ACCENT if accent else "#313244",
                          fg="#11111b" if accent else C_TEXT,
                          activebackground="#b4befe" if accent else "#45475a")
            b.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
            box.columnconfigure(col, weight=1)
            return b
        btn("🌐 打开仪表盘", self.open_dashboard, accent=True, row=0, col=0)
        btn("✏️ 写笔记", self.open_editor, row=0, col=1)
        btn("⚡ 快速记录", self.open_quick_record, row=1, col=0)
        btn("⚙️ 设置", self.open_settings, row=1, col=1)
        btn("🔽 缩到托盘", self.hide_to_tray, row=2, col=0)
        btn("🚪 退出程序", self.quit_app, row=2, col=1)

        self._status_label = tk.Label(r, text="托盘初始化中…", bg=C_BG, fg=C_DIM, font=FONT)
        self._status_label.pack(side="bottom", pady=(0, 8))

    def _refresh_today(self):
        """控制窗上的今日概要(读 tasks.json 实时算)"""
        try:
            st = bd.load_tasks()
            bucket = st.get("days", {}).get(bd.TODAY, [])
            dn = sum(1 for t in bucket if t.get("done"))
            tn = len(bucket)
            pred = planner.predict_tomorrow(st)["predicted"]
            self._today_label.config(
                text="今日任务：%d / %d 完成\n引擎建议明天：%d 条" % (dn, tn, pred))
        except Exception as e:
            self._today_label.config(text="概要加载失败: %s" % str(e)[:40])

    def _refresh_tray_status(self):
        if self._tray and self._tray.wait_ready(0):
            hotkey = "Ctrl+Shift+L ✓" if self._tray.hotkey_ok \
                else "热键被占用(托盘菜单可用)"
            self._url_label.config(text=self.url)
            self._status_label.config(text="托盘 %s · %s" %
                                      ("✓" if self._tray.tray_ok else "✗", hotkey))
        else:
            self.root.after(250, self._refresh_tray_status)

    # ---------------- 动作 ----------------
    def open_dashboard(self):
        webbrowser.open(self.url)

    def open_editor(self):
        webbrowser.open(self.url + "editor")

    def open_settings(self):
        webbrowser.open(self.url + "#setcard-wrap")   # 直达主页设置卡片锚点

    def hide_to_tray(self):
        self.root.withdraw()                           # 关闭按钮 = 缩到托盘, 不退出

    def restore_from_tray(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def handle_show_event(self, payload):
        if payload == "toggle":                        # Ctrl+Shift+L: 显<->隐
            if self.root.state() == "withdrawn":
                self.restore_from_tray()
            else:
                self.hide_to_tray()
        else:                                          # 托盘左键: 必定唤起
            self.restore_from_tray()

    # ---------------- 托盘菜单 ----------------
    def show_tray_menu(self, x, y):
        import ctypes                                  # 仅取 SetForegroundWindow 修菜单焦点怪癖
        m = tk.Menu(self.root, tearoff=0, bg="#313244", fg=C_TEXT,
                    activebackground="#45475a", activeforeground="#cdd6f4",
                    font=FONT, relief="flat")
        m.add_command(label="打开主界面", command=self.open_dashboard)
        m.add_command(label="快速记录今日完成", command=self.open_quick_record)
        m.add_separator()
        m.add_command(label="隐藏控制台", command=self.hide_to_tray)
        m.add_separator()
        m.add_command(label="退出", command=self.quit_app)
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.root.frame(), 16))
        except Exception:
            pass                                       # 焦点修正尽力而为, 不影响弹出
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # ---------------- 快速记录对话框 ----------------
    def open_quick_record(self):
        if self._quick is not None and self._quick.winfo_exists():
            self._quick.deiconify()
            self._quick.lift()
            return
        st = bd.load_tasks()
        bucket = st.get("days", {}).get(bd.TODAY, [])
        q = tk.Toplevel(self.root)
        q.title("⚡ 快速记录 · 今日完成")
        q.configure(bg=C_BG)
        q.geometry("420x%d+%d+%d" % (min(520, 130 + 44 * max(len(bucket), 1)),
                                     self.root.winfo_x() - 450,
                                     self.root.winfo_y()))
        q.transient(self.root)
        tk.Label(q, text="勾选=标记完成（实时写回 tasks.json）",
                 bg=C_BG, fg=C_DIM, font=FONT).pack(pady=(10, 4))
        if not bucket:
            tk.Label(q, text="今天还没有任务\n去 daily 笔记里写一条吧",
                     bg=C_BG, fg=C_TEXT, font=FONT_B, justify="center").pack(pady=20)
        self._task_vars = {}
        frame = tk.Frame(q, bg=C_BG)
        frame.pack(fill="both", expand=True, padx=12)
        for i, t in enumerate(bucket):
            var = tk.BooleanVar(value=bool(t.get("done")))
            self._task_vars[t["id"]] = (var, t)
            tk.Checkbutton(frame, text=t.get("text", "(无标题)"), variable=var,
                           bg=C_BG, fg=C_TEXT, activebackground=C_BG,
                           selectcolor="#313244", font=FONT, anchor="w",
                           wraplength=370, justify="left").pack(fill="x", pady=2)
            # 闭包绑定当前 var/tid(默认参数快照), 勾选即直写数据层
            var.trace_add("write",
                          lambda *_a, vv=var, tt=t["id"]: self._apply_toggle(tt, vv.get()))
        q.protocol("WM_DELETE_WINDOW", q.destroy)
        self._quick = q

    def _apply_toggle(self, tid, done):
        """快速记录勾选直写进程内数据层(不过 HTTP), 并同步控制窗概要"""
        st = bd.load_tasks()
        ok, dn, tn = bd.toggle(st, tid, done)
        if ok:
            self._refresh_today()
            if done:
                self.show_toast("✅ 已完成", "干得漂亮！今日 %d/%d 条" % (dn, tn))

    # ---------------- 提醒调度 ----------------
    def _tick_reminders(self):
        """每 60 秒一轮; preopen 快照每次都传(fired 记账保证只弹一次, 多传无害)"""
        try:
            msgs = rem_mod.run_checks(BASE, last_open_ts=self._preopen)
            for msg in msgs:
                self.show_toast(msg.get("title", "📌 提醒"),
                                msg.get("body", ""), on_click=self.open_dashboard)
        except Exception:
            pass                                       # 提醒失败绝不拖垮常驻壳
        self.root.after(60000, self._tick_reminders)

    # ---------------- Toast 通知 ----------------
    def show_toast(self, title, body, on_click=None, duration_ms=9000):
        """右下角无边框置顶小窗; 点击整条直达; 到时自灭; 多条向上堆叠"""
        try:
            alive = [t for t in self._toasts if t.winfo_exists()]
        except tk.TclError:
            alive = []
        self._toasts = alive
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)                     # 无边框
        win.attributes("-topmost", True)
        win.configure(bg=C_ACCENT)                     # 外圈当描边
        inner = tk.Frame(win, bg=C_CARD, padx=12, pady=9)
        inner.pack(expand=True, fill="both")
        tk.Label(inner, text=title, bg=C_CARD, fg=C_ACCENT,
                 font=FONT_B, anchor="w").pack(fill="x")
        lbl = tk.Label(inner, text=body, bg=C_CARD, fg=C_TEXT, font=FONT,
                       wraplength=310, justify="left")
        lbl.pack(fill="x")
        def close(_e=None):
            try:
                win.destroy()
            except tk.TclError:
                pass
        def click(_e):
            if on_click:
                try:
                    on_click()
                except Exception:
                    pass
            close()
        for widget in (win, inner, lbl):
            widget.bind("<Button-1>", click)
        win.after(duration_ms, close)
        win.update_idletasks()
        w = 340
        h = min(win.winfo_reqheight(), 140)
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = sw - w - 22
        y = sh - h - 52 - len(alive) * (h + 10)        # 已有 toast 则向上堆
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self._toasts.append(win)

    # ---------------- 后台循环 ----------------
    def _poll_queue(self):
        """消费托盘线程投来的事件(100ms 轮询; Tk 对象只在本线程触碰)"""
        try:
            while True:
                ev, payload = self._events.get_nowait()
                if ev == tray.EVENT_SHOW:
                    self.handle_show_event(payload)
                elif ev == tray.EVENT_MENU:
                    self.show_tray_menu(*payload)
        except queue.Empty:
            pass
        if not self._quitting:
            self.root.after(100, self._poll_queue)

    # ---------------- 退出 ----------------
    def quit_app(self):
        """唯一真退出入口: 停托盘 -> 停服务 -> 销毁 Tk。幂等防重入。"""
        if self._quitting:
            return
        self._quitting = True
        try:
            if self._tray:
                self._tray.stop(timeout=2.5)           # 摘图标+注销热键+收线程
        except Exception:
            pass
        try:
            self._srv.shutdown()                        # 结束 serve_forever 循环
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    # 全局日志配置: 错误写入 app.log, 不再静默丢失
    _setup_logging()
    args = sys.argv[1:]
    existing = find_running_server()
    if existing:                                        # 单实例: 已在跑就只开页面
        print("[single-instance] already running at " + existing)
        webbrowser.open(existing)
        return 0
    preopen = bd.touch_last_open()                      # 先抓旧值快照再覆盖(回归提醒契约)
    try:                                                # v1.4: 首次运行必须最先初始化结构
        import firstrun
        fw = firstrun.ensure_workspace(BASE)
        if fw["created"]:
            print("[firstrun]", "已创建:", ", ".join(fw["created"]))
    except Exception as _fe:
        print("[firstrun] skipped:", str(_fe)[:80])
        logging.error("Boundary error in main.firstrun: %s", _fe, exc_info=True)
    try:                                                # v1.1: 到点自动备份(24h 窗口)
        import backup as backup_mod
        bkp = backup_mod.maybe_backup(BASE)
        if bkp:
            print("[backup]", os.path.basename(bkp))
    except Exception as _be:
        print("[backup] skipped:", str(_be)[:80])
        logging.error("Boundary error in main.backup: %s", _be, exc_info=True)
    try:                                                # v1.1: 当周/当月报告缺才生成
        import reportio
        reps = reportio.ensure_reports(BASE)
        if reps["created"]:
            print("[reports]", ", ".join(reps["created"]))
    except Exception as _re:
        print("[reports] skipped:", str(_re)[:80])
        logging.error("Boundary error in main.reports: %s", _re, exc_info=True)
    try:                                                # v1.2: 周日自动薄弱点分析
        import weakspot
        ws = weakspot.weekly_analysis(BASE)
        if ws.get("ran") and ws.get("report"):
            print("[weakspot]", ws["report"],
                  ("插入 %d 条" % len(ws["added"])) if ws["added"] else "无薄弱点")
    except Exception as _we:
        print("[weakspot] skipped:", str(_we)[:80])
        logging.error("Boundary error in main.weakspot: %s", _we, exc_info=True)
    try:                                                # v1.3: 启动即构建全文索引
        import search as search_mod
        idx = search_mod.build_index(BASE)
        print("[search]", "docs =", idx["_stats"]["docs"])
    except Exception as _se:
        print("[search] skipped:", str(_se)[:80])
        logging.error("Boundary error in main.search_index: %s", _se,
                      exc_info=True)
    srv, port = bd.create_server()
    if not srv:
        print("[ERR] ports %d-%d all busy" % (bd.PORT0, bd.PORT0 + 5))
        return 1
    threading.Thread(target=srv.serve_forever, name="http-srv", daemon=True).start()
    url = "http://127.0.0.1:%d/" % port
    print("[OK] serving " + url)
    root = tk.Tk()
    app = ResidentApp(root, srv, url, preopen_snapshot=preopen)
    root._app = app                                     # 供退出闭包定位
    if "--open" in args:
        root.after(700, lambda: webbrowser.open(url))
    if "--smoke-exit" in args:
        root.after(5000, app.quit_app)                  # 冒烟: 全组件真实跑 5 秒后自退
    try:
        root.mainloop()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
