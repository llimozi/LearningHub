# -*- coding: utf-8 -*-
"""data.py —— 数据访问/IO 层（原 build_dashboard.py H 类, Phase 2.2 迁移）。

依赖: config + 标准库。不依赖其他 _app 内部模块。
注意: 统一通过模块对象动态访问 config（config.BASE / config.TASKS_FILE），
以便测试可 patch _app.config.<name> 做数据隔离（见 v18b_test 等）。
"""
import os
import sys
import json
import datetime

from _app import config


def asset_path(name):
    """只读资源解析: 源码态=BASE; 单文件打包态=随包解包目录(_MEIPASS)。
    与用户数据(BASE 侧, 可写可迁移)严格分流——资源跟程序走, 数据跟用户走。"""
    cand = os.path.join(config.BASE, name)
    if os.path.exists(cand):
        return cand
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        alt = os.path.join(mei, name)
        if os.path.exists(alt):
            return alt
    return cand


# CSS 模板解耦: 仪表盘 ~2400 行 CSS 独立为 templates/dashboard.css
# 渲染时读取并注入 <style id="varroot">, 不再内嵌于 Python 模板字符串
_DASHBOARD_CSS_CACHE = None   # 进程级缓存(文件无变化则不重读)

def _read_dashboard_css():
    """读取外部 CSS 文件(带缓存), 失败时返回空字符串(降级不影响功能)。"""
    global _DASHBOARD_CSS_CACHE
    if _DASHBOARD_CSS_CACHE is not None:
        return _DASHBOARD_CSS_CACHE
    for p in (os.path.join(config.BASE, "templates", "dashboard.css"),
              asset_path(os.path.join("templates", "dashboard.css"))):
        try:
            with open(p, encoding="utf-8") as f:
                _DASHBOARD_CSS_CACHE = f.read()
            return _DASHBOARD_CSS_CACHE
        except OSError:
            continue
    _DASHBOARD_CSS_CACHE = ""
    return _DASHBOARD_CSS_CACHE


_DASHBOARD_JS_CACHE = None


def _read_dashboard_js():
    """读取外部 JS 文件(带缓存), 失败时返回空字符串(降级不影响功能)。"""
    global _DASHBOARD_JS_CACHE
    if _DASHBOARD_JS_CACHE is not None:
        return _DASHBOARD_JS_CACHE
    for p in (os.path.join(config.BASE, "templates", "dashboard.js"),
              asset_path(os.path.join("templates", "dashboard.js"))):
        try:
            with open(p, encoding="utf-8") as f:
                _DASHBOARD_JS_CACHE = f.read()
            return _DASHBOARD_JS_CACHE
        except OSError:
            continue
    _DASHBOARD_JS_CACHE = ""
    return _DASHBOARD_JS_CACHE


# ---------------- 数据层 ----------------
def load_tasks():
    if os.path.exists(config.TASKS_FILE):
        with open(config.TASKS_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return {"version": 2, "days": {}, "log": []}


def save_tasks(st):
    """原子写入: 先写 .tmp 再 os.replace, 任何时刻磁盘上都有一份完整文件。"""
    tmp = config.TASKS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.TASKS_FILE)


# ---------------- STATUS.json 辅助(v1.0: last_open_ts 供回归提醒判断) ----------------
def load_status():
    """读总览快照; 缺失/损坏返回空 dict(utf-8-sig 兼容记事本 BOM)"""
    try:
        with open(config.STATUS_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def load_plan():
    """读四线并行计划(plan.json); 缺失/损坏返回空 dict(utf-8-sig 兼容记事本 BOM)"""
    try:
        with open(config.PLAN_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def save_status(data):
    """原子写入: 先写 .tmp 再 os.replace, 任何时刻磁盘上都有一份完整文件。"""
    tmp = config.STATUS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.STATUS_FILE)


def touch_last_open(learning_dir=None):
    """把 STATUS.last_open_ts 更新为现在, 返回旧值。
    返回的旧值是「本次打开之前最后活跃时刻」——resident 拿它做连续未打开判定,
    若先更新后读就会永远看到刚刚的自己, 回归提醒失灵。
    读写必须落在【同一个】p 上: 曾因读用参数目录、写走模块常量,
    测试数据打穿真实 STATUS.json(lessons_learned #003)。"""
    p = os.path.join(learning_dir or config.BASE, "STATUS.json")
    old = None
    data = {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        old = data.get("last_open_ts")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    data["last_open_ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(p, "w", encoding="utf-8-sig") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass                                    # 状态文件写失败不阻塞启动
    return old


def read_file(name):
    p = os.path.join(config.BASE, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


__all__ = [
    "asset_path", "_read_dashboard_css", "_read_dashboard_js", "load_tasks", "save_tasks",
    "load_status", "save_status", "touch_last_open", "read_file",
]
