# -*- coding: utf-8 -*-
"""settings_test.py —— 设置中心单元测试 (v1.0 · 纯标准库)
跑法A: pytest settings_test.py       跑法B: python settings_test.py (零依赖runner)
覆盖: 默认值模板 / 深合并 / 损坏容错(半截JSON·非dict) / 原子保存往返 /
      ensure 首次生成 / pythonw 推断 / 自启命令拼装(空格加引号) / 假注册表开关往返与幂等
"""
import json
import os
import shutil
import tempfile

from settings import (default_settings, load_settings, save_settings,
                      ensure_settings, settings_path, _to_pythonw,
                      build_autostart_command, get_autostart, set_autostart,
                      AUTOSTART_VALUE_NAME)


class FakeRegistry:
    """内存假注册表: 与 WinRegBackend 完全相同的 get/set/delete 接口面"""
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


def _write(path, text):
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)


def test_load_missing_returns_defaults_without_writing():
    tmp = tempfile.mkdtemp()
    try:
        s = load_settings(tmp)
        assert s == default_settings(), s
        assert not os.path.exists(settings_path(tmp)), "load 不应落地建文件, 创建归 ensure"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_corrupted_returns_defaults_and_backs_up():
    tmp = tempfile.mkdtemp()
    try:
        _write(settings_path(tmp), '{"autostart": tru')          # 半截 JSON
        s = load_settings(tmp)
        assert s["autostart"] is False and s["theme"] == "dark", s
        bad = os.path.join(tmp, "settings.json.bad")
        assert os.path.exists(bad), "坏文件应留档便于人工排查"
        with open(bad, encoding="utf-8-sig") as f:
            assert "autostart" in f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_non_dict_json_tolerated():
    tmp = tempfile.mkdtemp()
    try:
        for content in ("[1,2,3]", '"just a string"', "123"):
            _write(settings_path(tmp), content)
            s = load_settings(tmp)
            assert s["reminders"]["review_time"] == "20:00", (content, s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_file_deep_merged():
    tmp = tempfile.mkdtemp()
    try:
        _write(settings_path(tmp), json.dumps({"autostart": True}))
        s = load_settings(tmp)
        assert s["autostart"] is True, s                         # 用户值覆盖默认
        assert s["theme"] == "dark", s                           # 缺失字段补默认
        assert s["reminders"]["review_time"] == "20:00", s       # 嵌套块也完整
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_nested_reminders_merge_keeps_siblings():
    tmp = tempfile.mkdtemp()
    try:
        _write(settings_path(tmp), json.dumps({"reminders": {"review_time": "21:30"}}))
        s = load_settings(tmp)
        r = s["reminders"]
        assert r["review_time"] == "21:30", s                    # 改过的保留
        assert r["daily_first_open"] is True, s                  # 兄弟键不受牵连
        assert r["fired"] == {}, s
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_default_settings_fresh_copy_each_call():
    a = default_settings()
    a["theme"] = "hacked"
    a["reminders"]["review_time"] = "99:99"
    b = default_settings()
    assert b["theme"] == "dark" and b["reminders"]["review_time"] == "20:00", b


def test_save_load_roundtrip_and_no_tmp_leftover():
    tmp = tempfile.mkdtemp()
    try:
        data = default_settings()
        data["theme"] = "midnight-blue"
        data["reminders"]["review_time"] = "21:00"
        save_settings(tmp, data)
        s2 = load_settings(tmp)
        assert s2["theme"] == "midnight-blue" and s2["reminders"]["review_time"] == "21:00", s2
        assert not os.path.exists(settings_path(tmp) + ".tmp"), "临时文件必须被替换掉"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ensure_creates_default_file_only_once():
    tmp = tempfile.mkdtemp()
    try:
        s1 = ensure_settings(tmp)
        assert os.path.exists(settings_path(tmp)), "首次运行要生成默认文件"
        with open(settings_path(tmp), encoding="utf-8-sig") as f:
            assert json.load(f)["theme"] == "dark"
        _write(settings_path(tmp), json.dumps({"theme": "ink-green"}))
        s2 = ensure_settings(tmp)
        assert s2["theme"] == "ink-green", "已有配置不得被默认值覆盖"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_to_pythonw_prefers_sibling_when_exists():
    tmp = tempfile.mkdtemp()
    try:
        py = os.path.join(tmp, "python.exe")
        pw = os.path.join(tmp, "pythonw.exe")
        _write(py, ""); _write(pw, "")
        assert _to_pythonw(py) == pw, "pythonw 存在时必须优先(无黑窗)"
        os.remove(pw)
        assert _to_pythonw(py) == py, "只有 python.exe 时回退原样"
        _write(pw, "")
        assert _to_pythonw(pw) == pw, "本身就是 pythonw 则不动"
        other = os.path.join(tmp, "my_exe.exe")
        _write(other, "")
        assert _to_pythonw(other) == other, "非标准名的解释器不改写"
        always = lambda p: True                                  # 注入谓词: 视为存在
        assert _to_pythonw(r"C:\x y\python.exe", exists=always).endswith("pythonw.exe")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_autostart_command_quotes_and_prefers_pythonw():
    cmd = build_autostart_command(r"C:\Program Files\Python311\python.exe",
                                  r"D:\my dir\resident.py",
                                  exists=lambda p: True)
    assert cmd == (r'"C:\Program Files\Python311\pythonw.exe"'
                   r' "D:\my dir\resident.py"'), cmd             # 两段都带引号, 空格安全
    n_quotes = cmd.count('"')
    assert n_quotes == 4, cmd
    cmd2 = build_autostart_command(r"C:\PY\python.exe", r"D:\learning\resident.py",
                                   exists=lambda p: False)
    assert "python.exe" in cmd2 and "pythonw" not in cmd2, cmd2  # 无 pythonw 回退


def test_set_autostart_roundtrip_with_fake_registry():
    tmp = tempfile.mkdtemp()                                     # 造真实存在的解释器假文件对,
    try:                                                         # 让默认 exists 检查走真文件系统
        py = os.path.join(tmp, "python.exe")
        pw = os.path.join(tmp, "pythonw.exe")
        _write(py, "")
        _write(pw, "")
        reg = FakeRegistry()
        cmd = set_autostart(True, learning_dir=r"C:\LearningHub\learning",
                            reg=reg, exe=py)
        assert cmd and cmd.startswith('"'), cmd
        assert "pythonw.exe" in cmd and "resident.py" in cmd, cmd
        assert r"C:\LearningHub\learning" in cmd, cmd             # 脚本路径来自 learning 目录
        assert get_autostart(reg) == cmd
        back = set_autostart(False, reg=reg)
        assert back is None and get_autostart(reg) is None
        assert AUTOSTART_VALUE_NAME in reg.deleted
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_set_autostart_enable_is_idempotent():
    reg = FakeRegistry()
    c1 = set_autostart(True, learning_dir=r"C:\LearningHub\learning", reg=reg, exe=r"C:\PY\python.exe")
    c2 = set_autostart(True, learning_dir=r"C:\LearningHub\learning", reg=reg, exe=r"C:\PY\python.exe")
    assert c1 == c2 and len(reg.values) == 1, reg.values         # 开两次不产生重复项


def test_disable_autostart_when_missing_is_safe():
    reg = FakeRegistry()
    assert set_autostart(False, reg=reg) is None                 # 关一个不存在的东西不炸
    assert reg.deleted == [AUTOSTART_VALUE_NAME]


def test_bom_file_still_loads_not_treated_as_corrupted():
    """记事本保存的 JSON 带 UTF-8 BOM 头: 必须照常读取, 不得误判为损坏文件"""
    tmp = tempfile.mkdtemp()
    try:
        with open(settings_path(tmp), "w", encoding="utf-8-sig") as f:
            f.write(json.dumps({"theme": "ink-green"}))
        s = load_settings(tmp)
        assert s["theme"] == "ink-green", s
        assert not os.path.exists(os.path.join(tmp, "settings.json.bad")), \
            "带BOM的好文件被归档成坏件 = 静默丢用户数据"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_guide_done_flag_defaults_false_and_patchable():
    tmp = tempfile.mkdtemp()
    try:
        s = load_settings(tmp)
        assert s.get("guide_done") is False, "首次运行引导必须默认未完成"
        s["guide_done"] = True
        save_settings(tmp, s)
        assert load_settings(tmp)["guide_done"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_guide_done_flag_defaults_false_and_patchable():
    tmp = tempfile.mkdtemp()
    try:
        s = load_settings(tmp)
        assert s.get("guide_done") is False, "首次运行引导必须默认未完成"
        s["guide_done"] = True
        save_settings(tmp, s)
        assert load_settings(tmp)["guide_done"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
