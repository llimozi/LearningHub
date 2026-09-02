# -*- coding: utf-8 -*-
"""settings.py —— 设置中心 (v1.0 · 纯标准库)

职责:
  1. settings.json 读写: 默认值深合并(缺字段补默认) + 损坏容错
     (半截 JSON / 非 dict 一律回退默认, 坏内容留档 settings.json.bad 供人工排查);
     落盘走「临时文件 + os.replace」原子替换, 防止写一半断电损坏。
  2. 开机自启封装:
     - _to_pythonw(): 同目录 pythonw.exe 存在则优先(开机无控制台黑窗), 否则原样回退;
     - build_autostart_command(): 纯函数拼命令行, 两段路径都加引号(空格安全);
     - get_autostart()/set_autostart(): 注册表 HKCU Run 键读写。
     注册表操作收敛到 WinRegBackend 的小接口面(get/set/delete),
     测试注入内存假实现即可全流程验证, 不碰真实注册表。

公开 API:
  default_settings()                       -> dict   # 每次返回全新深拷贝
  settings_path(learning_dir)              -> str
  load_settings(learning_dir)              -> dict   # 只读不落地; 缺失/损坏都安全
  save_settings(learning_dir, data)        -> dict   # 原子落盘并返回
  ensure_settings(learning_dir)            -> dict   # 首次运行生成默认文件; 已有则读
  _to_pythonw(exe, exists=os.path.exists)  -> str
  build_autostart_command(exe, script, exists=os.path.exists) -> str
  resident_script_path(learning_dir=None)  -> str
  get_autostart(reg=None)                  -> str | None
  set_autostart(enable, learning_dir=None, reg=None, exe=None) -> str | None

数据结构(settings.json):
  version=1
  autostart: bool                     自启开关(注册表为准, 此处存偏好)
  theme: str                          主题选择(v1.0 占位, v1.3 启用)
  reminders.daily_first_open: bool    每日首次开机提醒
  reminders.review_near: bool         复习临近提醒(复习时段前30分钟)
  reminders.review_time: "HH:MM"      今日复习时段(默认20:00)
  reminders.away_nudge: bool          连续未打开回归提醒
  reminders.away_days: int            判定「未打开」的天数阈值(默认2)
  reminders.fired: {日期: [键]}       当日已弹记录, 防重弹, 跨天自动清理
"""
import json
import os
import sys

SETTINGS_NAME = "settings.json"
BAD_BACKUP_NAME = "settings.json.bad"
AUTOSTART_VALUE_NAME = "LearningHub"                      # 注册表值名(开始菜单->运行可见)
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
SCRIPT_NAME = "resident.py"

# v1.2 学习节奏自适应默认参数(存 settings.json 的 adaptive 块, 设置页可调)
DEFAULT_ADAPTIVE = {
    "enabled": True,
    "high_rate": 0.9,        # 完成率 ≥ 此值算「高日」
    "high_run": 3,           # 连续高日数 -> 次日加量
    "boost": 0.10,           # 加量幅度(+10%)
    "low_rate": 0.5,         # 完成率 ≤ 此值算「低日」
    "low_run": 2,            # 连续低日数 -> 次日减量
    "reduce": 0.20,          # 减量幅度(-20%) 并附休息建议
}


def default_settings():
    """默认配置模板。每次调用生成全新副本, 防止调用方改脏模板。"""
    return {
        "version": 1,
        "autostart": False,
        "theme": "dark",
        "adaptive": DEFAULT_ADAPTIVE,
        "guide_done": False,
        "reminders": {
            "daily_first_open": True,
            "review_near": True,
            "review_time": "20:00",
            "away_nudge": True,
            "away_days": 2,
            "fired": {}
        }
    }


def deep_merge(base, extra):
    """公开版递归合并(设置接口补丁用): extra 覆盖 base, dict 进嵌套, 其余整体替换"""
    return _deep_merge(base, extra)


def _deep_merge(base, extra):
    """递归合并: extra 覆盖 base; dict 进嵌套合并, 其余类型整体替换。"""
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def settings_path(learning_dir):
    return os.path.join(learning_dir, SETTINGS_NAME)


def _backup_corrupted(p):
    """坏文件留档(.bad 覆盖写), 尽力而为不抛——容错路径里再抛异常就本末倒置了。
    用 utf-8-sig 读: 记事本保存的文件带 BOM 头也能正确留档原文。"""
    try:
        with open(p, encoding="utf-8-sig") as f:
            raw = f.read()
        bad = os.path.join(os.path.dirname(p), BAD_BACKUP_NAME)
        with open(bad, "w", encoding="utf-8-sig") as f:
            f.write(raw)
    except Exception:
        pass


def load_settings(learning_dir):
    """读设置: 文件缺失 -> 默认; 半截JSON/非dict -> 留档坏件并回退默认;
    正常 -> 默认深合并用户值(缺字段补齐)。只读, 不创建文件。
    utf-8-sig 兼容记事本(带BOM)与程序(无BOM)两种写法。"""
    p = settings_path(learning_dir)
    if not os.path.exists(p):
        return default_settings()
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        _backup_corrupted(p)
        return default_settings()
    if not isinstance(data, dict):
        _backup_corrupted(p)
        return default_settings()
    return _deep_merge(default_settings(), data)


def save_settings(learning_dir, data):
    """原子保存: 先写 .tmp 再 os.replace, 任何时刻磁盘上都有一份完整文件。"""
    p = settings_path(learning_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return data


def ensure_settings(learning_dir):
    """首次运行生成默认文件; 已有则照常读取(绝不覆盖用户已有配置)。"""
    if not os.path.exists(settings_path(learning_dir)):
        return save_settings(learning_dir, default_settings())
    return load_settings(learning_dir)


# ---------------- 开机自启 ----------------
def _to_pythonw(exe, exists=os.path.exists):
    """python.exe -> 同目录 pythonw.exe(确认存在才换, 开机自启无黑窗); 其余原样返回。
    exists 参数供测试注入, 生产用真实 os.path.exists。"""
    d, b = os.path.split(exe)
    if b.lower() == "python.exe":
        cand = os.path.join(d, "pythonw.exe")
        if exists(cand):
            return cand
    return exe


def build_autostart_command(exe, script, exists=os.path.exists):
    """自启命令行纯函数: 解释器与脚本两段都加引号(路径含空格也安全)。"""
    return '"%s" "%s"' % (_to_pythonw(exe, exists), script)


class WinRegBackend(object):
    """真实注册表后端: HKCU Run 键下 LearningHub 值的 get/set/delete。
    winreg 延迟到实例化才导入——非 Windows 环境导入本模块不炸(测试机兼容)。"""

    def __init__(self):
        import winreg
        self._winreg = winreg

    def get(self, name):
        try:
            with self._winreg.OpenKey(self._winreg.HKEY_CURRENT_USER,
                                      RUN_KEY_PATH, 0, self._winreg.KEY_READ) as k:
                val, _typ = self._winreg.QueryValueEx(k, name)
                return val
        except OSError:
            return None                                   # 键或值不存在

    def set(self, name, value):
        with self._winreg.CreateKeyEx(self._winreg.HKEY_CURRENT_USER,
                                      RUN_KEY_PATH, 0, self._winreg.KEY_SET_VALUE) as k:
            self._winreg.SetValueEx(k, name, 0, self._winreg.REG_SZ, value)

    def delete(self, name):
        try:
            with self._winreg.OpenKey(self._winreg.HKEY_CURRENT_USER,
                                      RUN_KEY_PATH, 0, self._winreg.KEY_SET_VALUE) as k:
                self._winreg.DeleteValue(k, name)
        except OSError:
            pass                                          # 不存在 = 已删, 幂等


def resident_script_path(learning_dir=None):
    """resident.py 绝对路径; learning_dir 缺省时取本模块所在目录。"""
    base = learning_dir or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, SCRIPT_NAME)


def get_autostart(reg=None):
    reg = reg or WinRegBackend()
    return reg.get(AUTOSTART_VALUE_NAME)


def set_autostart(enable, learning_dir=None, reg=None, exe=None):
    """开: 写入命令行并返回它(界面显示用); 关: 删除值返回 None。
    reg/exe 可注入: 测试传 FakeRegistry 与固定解释器路径, 全程不碰真注册表。"""
    reg = reg or WinRegBackend()
    if enable:
        cmd = build_autostart_command(exe or sys.executable,
                                      resident_script_path(learning_dir))
        reg.set(AUTOSTART_VALUE_NAME, cmd)
        return cmd
    reg.delete(AUTOSTART_VALUE_NAME)
    return None
