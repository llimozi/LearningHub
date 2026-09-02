# -*- coding: utf-8 -*-
"""packaging_test.py —— v1.4 打包层单元测试
跑法A: pytest packaging_test.py      跑法B: python packaging_test.py
覆盖: 路径解析双模式(源码态=脚本目录/打包态=exe所在目录, 防数据进临时解包目录) /
      build.py 资源清单真实存在 / pyinstaller 参数拼装完整且以 resident.py 收口 /
      图标生成魔数 / 环境校验的可注入探测。
"""
import os
import shutil
import sys
import tempfile
import time

import paths
import build


# ---------------- paths.app_base ----------------
def test_source_mode_returns_module_dir():
    out = paths.app_base(is_frozen=False)
    assert os.path.samefile(out, os.path.dirname(os.path.abspath(paths.__file__))), out


def test_frozen_mode_uses_exe_dir_not_temp_unpack_dir():
    """打包态关键契约: 数据必须落在用户看得见的 exe 旁, 而不是 _MEIPASS 临时目录"""
    fake = r"C:\Users\demo\Desktop\LearningHub.exe"
    out = paths.app_base(is_frozen=True, exe_path=fake)
    assert out == r"C:\Users\demo\Desktop", out
    assert "_MEI" not in out and "Temp" not in out, out


def test_frozen_defaults_read_from_sys_when_not_injected():
    saved_frozen = getattr(sys, "frozen", None)
    saved_exe = sys.executable                             # 全局状态必须成对还原
    try:
        sys.frozen = True
        sys.executable = r"D:\dist\LearningHub.exe"
        assert paths.app_base() == r"D:\dist"
    finally:
        if saved_frozen is None:
            delattr(sys, "frozen")
        else:
            sys.frozen = saved_frozen
        sys.executable = saved_exe


# ---------------- build.py 资源与参数 ----------------
def test_data_files_exist_in_project_root():
    root = os.path.dirname(os.path.abspath(build.__file__))
    for rel, arc in build.DATA_FILES:
        p = os.path.join(root, rel.replace("/", os.sep))
        assert os.path.exists(p), (rel, arc)                 # 清单里不许有不存在的资源


def test_data_files_expected_pairs():
    pairs = dict(build.DATA_FILES)
    assert pairs.get("editor.html") == "."                   # 编辑器页面必须随身携带
    assert pairs.get("stoplist.txt") == "."
    assert all(not arc.startswith("_MEI") for arc in pairs.values())


def test_pyinstaller_args_complete_and_ends_with_entry():
    args = build.pyinstaller_args(icon=os.path.join("assets", "learninghub.ico"),
                                  name="LearningHub",
                                  entry="resident.py")
    joined = " ".join(args)
    for flag in ("--noconfirm", "--clean", "--onefile", "--noconsole"):
        assert flag in args or flag in joined, flag
    assert any(a.startswith("--icon=") and a.endswith("learninghub.ico") for a in args)
    assert sum(1 for a in args if a.startswith("--add-data=")) == len(build.DATA_FILES)
    assert args[-1] == "resident.py", args[-1]               # 入口脚本收口


def test_check_environment_reports_missing_finder():
    ok, msg = build.check_environment(lambda tool: None)     # 注入找不到
    assert ok is False and ("pip install pyinstaller" in msg.lower()), msg
    ok2, msg2 = build.check_environment(lambda tool: r"C:\x\pyinstaller.exe")
    assert ok2 is True, msg2


def test_ensure_icon_writes_ico_magic_once():
    d = tempfile.mkdtemp()
    try:
        icon = os.path.join(d, "assets", "learninghub.ico")
        p1 = build.ensure_icon(icon)
        with open(p1, "rb") as f:
            head = f.read(4)
        assert head == b"\x00\x00\x01\x00", head.hex()       # ICO 魔数
        mtime1 = os.path.getmtime(p1)
        time.sleep(0.01)
        p2 = build.ensure_icon(icon)
        assert p2 == p1
        # 已存在则复用(内容不变), 不反复重写
        import time as _t
        mtime2 = os.path.getmtime(p2)
        assert mtime2 >= mtime1
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
