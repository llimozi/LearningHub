# -*- coding: utf-8 -*-
"""resident_test.py —— v1.0 常驻层单元测试
跑法A: pytest resident_test.py      跑法B: python resident_test.py (零依赖runner)
覆盖: touch_last_open 旧值语义(回归提醒的命门) / 设置接口读写+自启联动(注入假注册表) /
      补丁深合并语义 / 注册表失败不炸接口。真实 HTTP 冒烟由 --smoke-exit 流程覆盖。
"""
import json
import os
import shutil
import tempfile

import build_dashboard as bd
import settings


class FakeRegistry:
    """与 settings_test 同款内存假注册表(本地重定义, 避免测试文件互相依赖)"""
    def __init__(self):
        self.values = {}
        self.deleted = []

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.deleted.append(name)
        self.values.pop(name, None)


class BoomRegistry:
    """模拟权限不足/企业策略拦截: set 与 delete 都抛 OSError"""
    def get(self, name):
        return None

    def set(self, name, value):
        raise OSError("Access is denied")

    def delete(self, name):
        raise OSError("Access is denied")


def _make_py_pair(tmp):
    """造 python.exe + pythonw.exe 假文件对, 让 pythonw 推断走真文件系统"""
    py = os.path.join(tmp, "python.exe")
    pw = os.path.join(tmp, "pythonw.exe")
    for p in (py, pw):
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("")
    return py


# ---------------- touch_last_open ----------------
def test_touch_last_open_first_call_returns_none_then_old_value():
    import time
    tmp = tempfile.mkdtemp()
    try:
        old1 = bd.touch_last_open(tmp)
        assert old1 is None, "首次运行之前没有旧值"
        with open(os.path.join(tmp, "STATUS.json"), encoding="utf-8-sig") as f:
            first = json.load(f)["last_open_ts"]
        time.sleep(1.1)                                  # 时间戳按秒截断, 隔开一秒防同秒相等
        old2 = bd.touch_last_open(tmp)
        assert old2 == first, "第二次必须返回上一次写入值(resident 快照契约)"
        current = json.load(open(os.path.join(tmp, "STATUS.json"),
                                 encoding="utf-8-sig"))["last_open_ts"]
        assert old2 != current, "旧值与新值必须可区分(否则回归提醒会认错自己)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_touch_last_open_preserves_other_status_fields():
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "STATUS.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"updated": "2026-08-22", "streak": 3}, f)
        bd.touch_last_open(tmp)
        with open(os.path.join(tmp, "STATUS.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        assert data["streak"] == 3 and data["updated"] == "2026-08-22", data
        assert "last_open_ts" in data, data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_touch_last_open_survives_missing_or_broken_status():
    tmp = tempfile.mkdtemp()
    broken = tempfile.mkdtemp()
    try:
        assert bd.touch_last_open(tmp) is None          # 无文件: 建新档不炸
        with open(os.path.join(broken, "STATUS.json"), "w", encoding="utf-8-sig") as f:
            f.write("{oops")
        assert bd.touch_last_open(broken) in (None,)     # 损坏文件: 视为无旧值
        with open(os.path.join(broken, "STATUS.json"), encoding="utf-8-sig") as f:
            assert "last_open_ts" in json.load(f)        # 且重建出可用快照
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(broken, ignore_errors=True)


# ---------------- 设置接口本体 ----------------
def test_api_get_settings_shape_and_defaults():
    tmp = tempfile.mkdtemp()
    try:
        d = bd.api_get_settings(learning_dir=tmp, reg=FakeRegistry())
        assert d["ok"] is True
        assert d["settings"]["theme"] == "dark"          # 无文件回默认
        assert d["autostart_registered"] is None         # 未登记自启
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_api_post_settings_patch_merges_and_persists():
    tmp = tempfile.mkdtemp()
    try:
        d = bd.api_post_settings(
            {"theme": "ink-green", "reminders": {"review_time": "21:15"}},
            learning_dir=tmp, reg=FakeRegistry())
        assert d["ok"] is True
        s = settings.load_settings(tmp)
        assert s["theme"] == "ink-green", s              # 补丁生效
        assert s["reminders"]["review_time"] == "21:15", s
        assert s["reminders"]["daily_first_open"] is True, s   # 兄弟键不受牵连
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_api_post_settings_autostart_toggle_syncs_registry():
    tmp = tempfile.mkdtemp()
    reg = FakeRegistry()
    try:
        pydir = os.path.join(tmp, "pydir")
        os.makedirs(pydir)
        py = _make_py_pair(pydir)
        d1 = bd.api_post_settings({"autostart": True},
                                  learning_dir=tmp, reg=reg, exe=py)
        assert d1["ok"] and d1["autostart_error"] is None
        cmd = d1["autostart_registered"]
        assert cmd and "pythonw.exe" in cmd and "resident.py" in cmd, cmd
        assert reg.values[settings.AUTOSTART_VALUE_NAME] == cmd
        assert settings.load_settings(tmp)["autostart"] is True
        d2 = bd.api_post_settings({"autostart": True},
                                  learning_dir=tmp, reg=reg, exe=py)
        assert len(reg.values) == 1                      # 重复开启不产生第二条登记
        assert d2["ok"] and d2["autostart_error"] is None
        # 幂等语义: 值无变化 -> 不重写注册表 -> 不回显命令(d2.autostart_registered 为 None)
        d3 = bd.api_post_settings({"autostart": False},
                                  learning_dir=tmp, reg=reg, exe=py)
        assert d3["autostart_registered"] is None        # 关闭返回 None
        assert settings.AUTOSTART_VALUE_NAME not in reg.values
        assert settings.load_settings(tmp)["autostart"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_api_post_settings_registry_failure_reported_not_fatal():
    tmp = tempfile.mkdtemp()
    try:
        d = bd.api_post_settings({"autostart": True},
                                 learning_dir=tmp, reg=BoomRegistry(),
                                 exe=r"C:\x\python.exe")
        assert d["ok"] is True                           # 接口不因注册表失败而失败
        assert "denied" in (d["autostart_error"] or ""), d
        assert settings.load_settings(tmp)["autostart"] is True   # 偏好保留, 系统状态解耦
        d2 = bd.api_post_settings({"autostart": False},
                                  learning_dir=tmp, reg=BoomRegistry(),
                                  exe=r"C:\x\python.exe")
        assert d2["ok"] is True and d2["autostart_error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_api_post_settings_rejects_non_dict_patch():
    d = bd.api_post_settings([1, 2, 3], learning_dir=tempfile.gettempdir(),
                             reg=FakeRegistry())
    assert d["ok"] is False and "对象" in d["err"], d


def test_settings_deep_merge_public_wrapper():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    out = settings.deep_merge(base, {"a": {"b": 9}})
    assert out["a"] == {"b": 9, "c": 2} and out["d"] == 3, out


# ---------------- 单实例探测 ----------------
def test_find_running_server_none_on_dead_ports():
    from resident import find_running_server
    url = find_running_server(port0=57590, tries=2, timeout=0.3)
    assert url is None                                   # 死端口段必须安静返回 None


def test_find_running_server_detects_live_instance():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from resident import find_running_server

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)    # 系统分配空闲端口
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = find_running_server(port0=port, tries=1, timeout=1.0)
        assert url == "http://127.0.0.1:%d/" % port, url
    finally:
        srv.shutdown()


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
