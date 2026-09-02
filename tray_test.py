# -*- coding: utf-8 -*-
"""tray_test.py —— 托盘模块单元测试 (v1.0 · 纯标准库)
跑法A: pytest tray_test.py     跑法B: python tray_test.py (零依赖runner)
本文件覆盖:
  【基础层】ICO 字节格式(魔数/目录表/数据自洽/像素透明度) /
            NOTIFYICONDATAW 结构体(cbSize 工厂不变量) / 热键与消息常量契约。
  【交互层】真实 Windows 集成: 托盘挂载/消息窗口创建/三类事件分发/优雅退出。
            (非 Windows 环境自动跳过)
"""
import os
import queue as queue_mod
import shutil
import struct
import sys
import tempfile
import ctypes

from tray import (NOTIFYICONDATAW, new_nid, TrayIcon,
                  make_ico_bytes, save_ico, render_icon_bgra,
                  WM_HOTKEY, WM_TRAY_CALLBACK, WM_LBUTTONUP, WM_RBUTTONUP,
                  NIM_ADD, NIM_DELETE, NIF_MESSAGE, NIF_ICON, NIF_TIP,
                  MOD_CONTROL, MOD_SHIFT,
                  HOTKEY_ID, HOTKEY_MODS, HOTKEY_VK,
                  EVENT_SHOW, EVENT_MENU)


# ---------------- ICO 字节格式 ----------------
def test_ico_magic_and_entry_count():
    raw = make_ico_bytes((16, 32))
    assert raw[:4] == b"\x00\x00\x01\x00", raw[:4].hex()      # ICONDIR: 保留0 + 类型1(icon)
    count, = struct.unpack_from("<H", raw, 4)
    assert count == 2, count                                   # 两个尺寸两个目录项


def test_ico_directory_entries_self_consistent():
    sizes = (16, 32)
    raw = make_ico_bytes(sizes)
    offset = 6
    prev_end = 6 + 16 * len(sizes)                             # 数据区从目录表后开始
    for i, s in enumerate(sizes):
        w, h, cc, res, planes, bits, dlen, doff = struct.unpack_from("<BBBBHHII", raw, offset)
        assert (w, h) == (s, s), (i, w, h)                     # <256 尺寸原样入目录
        assert (cc, res) == (0, 0)
        assert planes == 1 and bits == 32, (planes, bits)
        assert doff == prev_end, (i, doff, prev_end)           # 数据紧挨着排布
        img = raw[doff:doff + dlen]
        # 图内 BITMAPINFOHEADER 自洽: biHeight = 尺寸*2(XOR面+AND面), 32bpp
        bisz, bw, bh, bplane, bbits = struct.unpack_from("<IiiHH", img, 0)
        assert bisz == 40 and bw == s and bh == s * 2, (bisz, bw, bh)
        assert bplane == 1 and bbits == 32
        # 数据长度公式: 头40 + BGRA像素 + AND掩码(行步长按32位对齐)
        stride = ((s + 31) // 32) * 4
        assert dlen == 40 + s * s * 4 + stride * s, dlen
        prev_end = doff + dlen
        offset += 16
    assert prev_end == len(raw), (prev_end, len(raw))          # 文件总长无冗余


def test_ico_pixels_center_opaque_corner_transparent():
    size = 32
    px = render_icon_bgra(size)
    assert len(px) == size * size * 4
    def at(x, y):                                              # 输出为自下而上, 换算行号
        row = size - 1 - y
        o = (row * size + x) * 4
        return px[o], px[o + 1], px[o + 2], px[o + 3]          # B,G,R,A
    c = at(size // 2, size // 2)
    assert c[3] == 255, c                                      # 中心必须不透明
    assert c[:3] != (0, 0, 0), c                               # 中心不是黑洞(有底色或标记色)
    corner = at(0, 0)
    assert corner[3] == 0, corner                              # 圆角外完全透明


def test_ico_empty_sizes_rejected():
    try:
        make_ico_bytes(())
        assert False, "空尺寸列表应抛 ValueError"
    except ValueError:
        pass


def test_save_ico_roundtrip(tmpdir=None):
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "icon.ico")
        out = save_ico(p)
        assert out == p and os.path.exists(p)
        with open(p, "rb") as f:
            assert f.read() == make_ico_bytes((16, 32))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- NOTIFYICONDATAW 结构体 ----------------
def test_nid_factory_sets_cbsize_to_real_sizeof():
    """cbSize 必须 = 结构体真实字节数——这是 Shell_NotifyIconW 的硬性约定"""
    nid = new_nid(tip="学习仪表盘")
    assert nid.cbSize == ctypes_sizeof_nid(), (nid.cbSize,)


def ctypes_sizeof_nid():
    import ctypes
    return ctypes.sizeof(NOTIFYICONDATAW)


def test_nid_fields_roundtrip():
    nid = new_nid(u_id=7, callback_msg=WM_TRAY_CALLBACK, tip="托盘")
    assert nid.uID == 7
    assert nid.uCallbackMessage == WM_TRAY_CALLBACK
    assert nid.szTip == "托盘"
    flags = nid.uFlags
    assert flags & NIF_MESSAGE and flags & NIF_TIP, hex(flags)  # 用到哪项就声明哪项


def test_nid_tip_overlong_truncated_safely():
    long_tip = "超" * 200                                       # 远超 63 字符容量
    nid = new_nid(tip=long_tip)                                # 不得抛异常
    assert len(nid.szTip) <= 63, len(nid.szTip)


def test_nid_flags_combination_all_three():
    nid = new_nid(tip="学习仪表盘", with_icon=True)             # 三块数据都用了
    assert nid.uFlags == (NIF_MESSAGE | NIF_ICON | NIF_TIP), hex(nid.uFlags)


# ---------------- 常量契约 ----------------
def test_hotkey_constants_match_spec():
    assert MOD_CONTROL | MOD_SHIFT == 0x0006, "Ctrl+Shift 组合码"
    assert HOTKEY_MODS == MOD_CONTROL | MOD_SHIFT
    assert HOTKEY_VK == ord("L") == 0x4C, HOTKEY_VK
    assert HOTKEY_ID == 1


def test_message_ids_mutually_distinct():
    """回调消息/热键消息/鼠标键值互不相等——防复制粘贴改错常量的低级事故"""
    ids = [WM_HOTKEY, WM_TRAY_CALLBACK, WM_LBUTTONUP, WM_RBUTTONUP]
    assert len(ids) == len(set(ids)), ids
    assert WM_HOTKEY == 0x0312
    assert WM_TRAY_CALLBACK > 0x8000, "回调消息必须在 WM_APP 区间, 避免撞系统保留值"


def test_tray_lifecycle_constants():
    assert NIM_ADD == 0 and NIM_DELETE == 2                    # 挂载/删除动作码
    assert {NIF_MESSAGE, NIF_ICON, NIF_TIP} == {1, 2, 4}


def test_event_names_are_the_resident_contract():
    assert EVENT_SHOW == "show"                                # 左键单击/热键 -> 唤起主窗
    assert EVENT_MENU == "menu"                                # 右键 -> 弹菜单(payload=(x,y))


# ---------------- 交互层集成(真实 Windows, 挂真图标/真窗口, 无需人工干预) ----------------
def _win_only():
    if sys.platform != "win32":
        import pytest
        pytest.skip("托盘交互层仅 Windows 可测")


def test_tray_lifecycle_and_event_dispatch():
    _win_only()
    q = queue_mod.Queue()
    t = TrayIcon("单测托盘", q)
    user32 = ctypes.windll.user32
    try:
        t.start()
        assert t.wait_ready(3.0), "托盘线程 3 秒内未就绪"
        assert t.hwnd, "消息窗口未创建"
        assert t.tray_ok is True, "Shell_NotifyIconW 挂载失败"
        # 左键单击 -> (show, "raise") 必定唤起
        user32.PostMessageW(t.hwnd, WM_TRAY_CALLBACK, 0, WM_LBUTTONUP)
        ev, payload = q.get(timeout=2.0)
        assert (ev, payload) == (EVENT_SHOW, "raise"), (ev, payload)
        # 右键 -> (menu, (x,y)) 真实屏幕坐标
        user32.PostMessageW(t.hwnd, WM_TRAY_CALLBACK, 0, WM_RBUTTONUP)
        ev, payload = q.get(timeout=2.0)
        assert ev == EVENT_MENU and len(payload) == 2 \
            and all(isinstance(v, int) for v in payload), (ev, payload)
        # 热键消息直投窗口(与注册成败解耦, 只验分发路径) -> (show, "toggle")
        user32.PostMessageW(t.hwnd, WM_HOTKEY, HOTKEY_ID, 0)
        ev, payload = q.get(timeout=2.0)
        assert (ev, payload) == (EVENT_SHOW, "toggle"), (ev, payload)
        assert isinstance(t.hotkey_ok, bool)               # 被占用时 False 但不影响其余功能
    finally:
        ok = t.stop()
    assert ok, "托盘线程未在超时内退出"
    assert not t.is_alive()
    assert t.hwnd is None, "退出后消息窗口句柄应已销毁"


def test_tray_double_start_and_idempotent_stop():
    _win_only()
    q = queue_mod.Queue()
    t = TrayIcon("单测托盘二", q)
    try:
        t.start()
        assert t.wait_ready(3.0)
        first_thread = t._thread
        t.start()                                          # 二次 start 不换线程
        assert t._thread is first_thread
        assert t.stop() and t.stop()                       # 双重 stop 幂等
    finally:
        t.stop()


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
