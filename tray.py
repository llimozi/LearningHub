# -*- coding: utf-8 -*-
"""tray.py —— 系统托盘与全局热键 (v1.0 · 纯 ctypes, 零第三方依赖)

分层设计:
  【基础层 · 已交付】
      Win32 常量(手抄 winuser.h/shellapi.h, 不引 win32con) /
      NOTIFYICONDATAW 结构体与 new_nid 工厂(cbSize 不变量集中管理) /
      纯 Python ICO 字节生成器(圆角方块+对勾, 免图片素材, LoadImage 可直接加载)。
      以上全部可离线单测(tray_test.py), 不触发任何真实系统调用。
  【交互层 · 已交付】TrayIcon 类:
      独立线程建消息窗口(RegisterClassW/CreateWindowExW) -> Shell_NotifyIconW 挂图标 ->
      GetMessageW 循环 -> 左键/右键/Ctrl+Shift+L 解析 -> queue.Queue 投递 Tk 主线程 ->
      stop() 优雅退出(NIM_DELETE + UnregisterHotKey + DestroyWindow + WM_QUIT)。

队列契约(resident 依赖):
  queue.get() -> (EVENT_SHOW, "raise")    托盘左键单击 -> 必定唤起主窗
  queue.get() -> (EVENT_MENU, (x, y))     右键 -> Tk 主线程在 (x,y) 弹暗色菜单

线程铁律: 本类所有 Win32 调用都发生在托盘线程; 事件只经队列过河,
Tk 主线程绝不直接碰托盘句柄, 托盘线程绝不碰任何 Tk 对象。
"""
import os
import struct
import ctypes
import tempfile
import threading
from ctypes import wintypes

# ---------------- Win32 常量 ----------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111                     # 菜单命令(交互层使用)
WM_LBUTTONUP = 0x0202                   # 托盘左键单击
WM_RBUTTONUP = 0x0205                   # 托盘右键单击
WM_APP = 0x8000
WM_TRAY_CALLBACK = WM_APP + 1           # 托盘回调自定义消息(WM_APP 区间是应用安全区)
WM_HOTKEY = 0x0312                      # RegisterHotKey 命中后投递的消息
WM_QUIT = 0x0012                        # PostThreadMessageW 投它可终结 GetMessage 循环

IDI_APPLICATION = 32512                 # 系统默认图标资源 id(图标文件加载失败时兜底)

NIM_ADD = 0x0000                        # Shell_NotifyIconW 动作码: 挂载
NIM_MODIFY = 0x0001                     #                        : 改动
NIM_DELETE = 0x0002                     #                        : 移除

NIF_MESSAGE = 0x0001                    # NOTIFYICONDATA.uFlags 位: 启用回调消息
NIF_ICON = 0x0002                       #                          : 启用图标
NIF_TIP = 0x0004                        #                          : 启用悬停提示

HWND_MESSAGE = -3                       # 消息专用窗口父句柄(不可见, 收消息专用)
IMAGE_ICON = 1                          # LoadImage 类型: 图标
LR_LOADFROMFILE = 0x0010                # LoadImage 标志: 从 .ico 文件加载
LR_DEFAULTSIZE = 0x0040

MOD_ALT = 0x0001                        # RegisterHotKey 修饰键位
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
HOTKEY_ID = 1                           # 本应用唯一热键 id(同一进程内不重复即可)
HOTKEY_MODS = MOD_CONTROL | MOD_SHIFT   # v1.0 规格: Ctrl+Shift+L 呼出/隐藏主窗
HOTKEY_VK = ord("L")                    # 0x4C

TIP_MAX_CHARS = 63                      # szTip 是 WCHAR[64], 含结尾 NUL 只能放 63 字符

# ---------------- 队列事件契约 ----------------
EVENT_SHOW = "show"                     # payload: "raise"=左键唤起 / "toggle"=热键切换
EVENT_MENU = "menu"                     # payload=(x, y) 屏幕坐标(GetCursorPos 所得)


# ---------------- NOTIFYICONDATAW 结构体与工厂 ----------------
class NOTIFYICONDATAW(ctypes.Structure):
    """shellapi.h 的 NOTIFYICONDATAW 完整版(含 guidItem 尾部, 与 SDK 布局一致)。
    Windows 按 cbSize 识别版本, 工厂统一填 sizeof 保证自洽。"""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 64),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("unionVersion", wintypes.UINT),          # uVersion/uTimeout 共用体
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
    ]


def new_nid(u_id=0, callback_msg=WM_TRAY_CALLBACK, tip="",
            hwnd=None, icon=None, with_icon=False):
    """托盘结构体工厂: cbSize 恒等于真实 sizeof;
    用到哪块数据就声明哪个 NIF_* 位(tip 截断到安全长度, 绝不越界)。"""
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    if hwnd is not None:
        nid.hWnd = hwnd
    nid.uID = u_id
    nid.uCallbackMessage = callback_msg
    flags = NIF_MESSAGE                            # 回调消息是托盘的立身之本, 恒声明
    if tip:
        nid.szTip = str(tip)[:TIP_MAX_CHARS]
        flags |= NIF_TIP
    if icon is not None:
        nid.hIcon = icon
        flags |= NIF_ICON
    elif with_icon:                                # 先占位, hIcon 由调用方后填
        flags |= NIF_ICON
    nid.uFlags = flags
    return nid


# ---------------- ICO 字节生成器(纯手写格式) ----------------
_ICO_HEADER = struct.Struct("<HHH")                # 保留字/类型(icon=1)/条目数
_DIR_ENTRY = struct.Struct("<BBBBHHII")            # 宽/高/色数/保留/面数/位深/数据长/偏移


def _line_cells(p0, p1, size):
    """归一化坐标线段 -> 整数像素格集合(密采样保证视觉连续)"""
    (ax, ay), (bx, by) = p0, p1
    steps = max(int(max(abs(bx - ax), abs(by - ay)) * size) * 2, 1)
    cells = set()
    for i in range(steps + 1):
        t = i / steps
        cells.add((round((ax + (bx - ax) * t) * size),
                   round((ay + (by - ay) * t) * size)))
    return cells


def _dilate(cells, radius):
    """笔画加粗: 每个格子向四周膨胀 radius 格(方形核)"""
    out = set()
    for (x, y) in cells:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                out.add((x + dx, y + dy))
    return out


def _inside_rounded(x, y, size, margin, rad):
    """点是否落在圆角方块内(margin 内缩 + 四角半径 rad)"""
    lo, hi = margin, size - 1 - margin
    if not (lo <= x <= hi and lo <= y <= hi):
        return False
    if x < lo + rad:                               # 左侧圆角带: 找左上/左下圆心
        cx = lo + rad
    elif x > hi - rad:                             # 右侧圆角带
        cx = hi - rad
    else:
        return True                                # 中部竖直区: 直边, 直接算内部
    if y < lo + rad:
        cy = lo + rad
    elif y > hi - rad:
        cy = hi - rad
    else:
        return True                                # 角带内的水平中部: 直边
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= rad * rad          # 角部: 到圆心的距离判定


def render_icon_bgra(size, bg=(137, 180, 250), mark=(17, 17, 27)):
    """渲染 size×size 像素, 返回【自下而上】BGRA 字节流(恰为 ICO 的 XOR 位面)。
    图案: 圆角方块底色(#89b4fa 学习蓝) + 深色对勾(完成主题)。
    bg/mark 均为 (R,G,B) 0~255。"""
    if size <= 0:
        raise ValueError("尺寸必须为正整数")
    margin = max(1, size // 16)
    rad = max(2, size // 5)
    thick = max(1, size // 9)
    stroke = _dilate(_line_cells((0.26, 0.54), (0.44, 0.72), size)
                     | _line_cells((0.44, 0.72), (0.78, 0.30), size), thick)
    buf = bytearray()
    for y in range(size - 1, -1, -1):              # BMP 行序自下而上
        for x in range(size):
            if (x, y) in stroke:
                r, g, b = mark
                a = 255
            elif _inside_rounded(x, y, size, margin, rad):
                r, g, b = bg
                a = 255
            else:                                  # 圆角外全透明(任务栏/托盘不出现黑角)
                r = g = b = a = 0
            buf += bytes((b, g, r, a))             # 内存序 B,G,R,A
    return bytes(buf)


def make_ico_bytes(sizes=(16, 32), bg=(137, 180, 250), mark=(17, 17, 27)):
    """组装完整 .ico 文件字节: ICONDIR + 目录表(小→大尺寸) + 各尺寸图像数据。
    图像数据 = BITMAPINFOHEADER(40B, biHeight=高×2: XOR面+AND面) + BGRA像素 + AND掩码。"""
    sizes = tuple(sizes)
    if not sizes:
        raise ValueError("至少需要一个图标尺寸")
    images = []
    for s in sizes:
        px = render_icon_bgra(s, bg, mark)
        stride = ((s + 31) // 32) * 4               # AND 掩码行按 32 位对齐
        mask = bytes(stride * s)                    # 32bpp 自带 alpha, 掩码全 0 即可
        bih = struct.pack("<IiiHHIIiiII",
                          40,                       # biSize
                          s,                        # biWidth
                          s * 2,                    # biHeight: XOR+AND 两面
                          1,                        # biPlanes
                          32,                       # biBitCount
                          0,                        # biCompression = BI_RGB
                          len(px) + len(mask),      # biSizeImage
                          0, 0, 0, 0)
        images.append(bih + px + mask)
    header = _ICO_HEADER.pack(0, 1, len(sizes))
    offset = len(header) + _DIR_ENTRY.size * len(sizes)
    directory = b""
    for s, img in zip(sizes, images):
        directory += _DIR_ENTRY.pack(s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    return header + directory + b"".join(images)


def save_ico(path, sizes=(16, 32)):
    """落一份真实 .ico 文件(交互层用 LoadImage+LR_LOADFROMFILE 加载它), 返回路径"""
    with open(path, "wb") as f:
        f.write(make_ico_bytes(sizes))
    return path


# ================= 交互层: TrayIcon(托盘线程完整生命周期) =================
LRESULT = ctypes.c_ssize_t              # LONG_PTR: 64 位下指针宽度, 返回值不能截断
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- 函数原型定型: 64 位下不声明 restype 默认按 32 位 int 截断指针/句柄, 必须显式 ----
_user32.DefWindowProcW.restype = LRESULT
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.PostQuitMessage.argtypes = [wintypes.INT]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.LoadIconW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]   # 第二参传 MAKEINTRESOURCE
_user32.DestroyIcon.argtypes = [wintypes.HANDLE]
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


class TrayIcon(object):
    """托盘图标 + 全局热键的完整生命周期(独立守护线程 + 事件队列)。

    用法(Tk 主线程):
        q = queue.Queue()
        tray = TrayIcon("学习仪表盘", q).start()
        tray.wait_ready()
        # ... root.after 轮询 q: (EVENT_SHOW, "raise"/"toggle") / (EVENT_MENU, (x,y))
        tray.stop()      # 退出前调用: 摘图标+注销热键+结束线程

    失败语义: 图标加载失败兜底系统默认图标; 热键被占用则 hotkey_ok=False
    但托盘与右键菜单照常工作; Shell_NotifyIconW 失败则 tray_ok=False 不抛异常。
    """

    def __init__(self, tip, events, enable_hotkey=True):
        self._tip = str(tip)[:TIP_MAX_CHARS]
        self._events = events                       # queue.Queue, 只由本类 put、主线程 get
        self._enable_hotkey = enable_hotkey
        self._class_name = "LearningHubTrayWnd_%d" % id(self)   # 每实例唯一, 防 WNDPROC 错绑
        self._thread = None
        self._thread_id = 0
        self.hwnd = None                            # 就绪后可读(测试/调试用)
        self.tray_ok = False                        # NIM_ADD 是否成功
        self.hotkey_ok = False                      # RegisterHotKey 是否成功
        self._ready = threading.Event()
        self._wndproc_ref = WNDPROC(self._on_message)   # 强引用防 GC——回调被回收=崩溃
        self._hicon = None
        self._ico_path = None
        self._nid = None

    # ---------- 生命周期(主线程侧) ----------
    def start(self):
        """启动托盘线程, 立即返回 self; 用 wait_ready() 等就绪"""
        if self.is_alive():
            return self                             # 幂等: 已在跑就不另起线程
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="tray-loop", daemon=True)
        self._thread.start()
        return self

    def wait_ready(self, timeout=3.0):
        """等托盘挂载完成(成功或失败结论落地)"""
        return self._ready.wait(timeout)

    def stop(self, timeout=3.0):
        """优雅退出: 投 WM_QUIT 终结消息循环, 清理由托盘线程自己在收尾时做。
        返回 True 表示线程已在超时内结束。幂等: 可安全多次调用。"""
        if self.is_alive() and self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout)
        return not self.is_alive()

    def is_alive(self):
        return bool(self._thread and self._thread.is_alive())

    # ---------- 托盘线程侧 ----------
    def _run(self):
        try:
            self._thread_id = _kernel32.GetCurrentThreadId()
            hinst = _kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.lpszClassName = self._class_name
            wc.hInstance = hinst
            _user32.RegisterClassW(ctypes.byref(wc))    # 重复注册失败无妨, 类名唯一
            self.hwnd = _user32.CreateWindowExW(
                0, self._class_name, "LearningHub tray", 0,
                0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
            if not self.hwnd:
                self._ready.set()                       # 建窗失败: 放弃但绝不拖死主程序
                return
            if self._enable_hotkey:
                self.hotkey_ok = bool(_user32.RegisterHotKey(
                    self.hwnd, HOTKEY_ID, HOTKEY_MODS, HOTKEY_VK))
            self._add_icon()
        finally:
            self._ready.set()                           # 无论成败, 结论必须让主线程等到
        if not self.hwnd:
            return
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        self._cleanup()                                 # GetMessage 收到 WM_QUIT 后到这里

    def _add_icon(self):
        """生成 .ico -> LoadImage 加载 -> NIM_ADD 挂上任务栏通知区"""
        try:
            self._ico_path = save_ico(os.path.join(tempfile.gettempdir(),
                                                   "learning_hub_tray.ico"))
            self._hicon = _user32.LoadImageW(None, self._ico_path, IMAGE_ICON, 0, 0,
                                             LR_LOADFROMFILE | LR_DEFAULTSIZE)
        except OSError:
            self._hicon = None                          # 临时目录不可写等极端情况走兜底
        if not self._hicon:
            self._hicon = _user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION))
        self._nid = new_nid(u_id=1, tip=self._tip, hwnd=self.hwnd, icon=self._hicon)
        self.tray_ok = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)))

    def _on_message(self, hwnd, umsg, wparam, lparam):
        """窗口过程(托盘线程): 解析三类事件投递队列。回调里禁止抛异常穿进 Win32。"""
        try:
            if umsg == WM_TRAY_CALLBACK:
                if lparam == WM_LBUTTONUP:              # 单击左键 = 必定唤起(v1.0 规格)
                    self._events.put((EVENT_SHOW, "raise"))
                elif lparam == WM_RBUTTONUP:            # 右键 = 弹菜单, 带光标屏幕坐标
                    pt = wintypes.POINT()
                    _user32.GetCursorPos(ctypes.byref(pt))
                    self._events.put((EVENT_MENU, (int(pt.x), int(pt.y))))
            elif umsg == WM_HOTKEY and wparam == HOTKEY_ID:
                self._events.put((EVENT_SHOW, "toggle"))  # Ctrl+Shift+L: 显隐切换语义
            elif umsg == WM_DESTROY:
                _user32.PostQuitMessage(0)
        except Exception:
            pass                                        # 队列满等极端情况: 丢事件保进程
        return _user32.DefWindowProcW(hwnd, umsg, wparam, lparam)

    def _cleanup(self):
        """摘图标 -> 注销热键 -> 销毁图标句柄 -> 删临时文件 -> 销毁消息窗口。
        全程尽力而为逐项保护: 退出路径上的失败不允许打断后续清理。"""
        try:
            if self._nid is not None:                   # 先摘图标: 否则退出后留幽灵图标直到悬停才消失
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                self._nid = None
            if self.hotkey_ok and self.hwnd:
                _user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
                self.hotkey_ok = False
        finally:
            if self._hicon:
                _user32.DestroyIcon(self._hicon)
                self._hicon = None
            if self._ico_path:
                try:
                    os.remove(self._ico_path)
                except OSError:
                    pass
                self._ico_path = None
            if self.hwnd:
                _user32.DestroyWindow(self.hwnd)
                self.hwnd = None
