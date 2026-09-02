# -*- coding: utf-8 -*-
r"""health_check.py —— 自检脚本 (v1.4 · 纯标准库)

用法: python health_check.py            # 检查并打印报告; 硬失败退出码 1, 否则 0
      python health_check.py --dir X    # 指定学习目录(默认程序所在目录)

检查项(级别 ok / warn / fail):
  核心文件   tasks.json·settings.json·STATUS.json·daily\ 是否齐备      [fail]
  JSON完整性 上述文件+knowledge/analysis 能否正常解析(损坏=数据风险)     [fail]
  磁盘空间   应用目录所在盘剩余 ≥500MB(可调)                            [fail]
  服务端口   8765 是否有实例在跑                                        [info]
  备份状态   backup\ 是否已有备份                                       [warn]

公开 API: check_core_files / check_json_integrity / check_disk /
          check_port / exit_code_for(results) —— 均可注入依赖便于测试。
"""
import json
import os
import socket
import sys

import paths

MIN_FREE_MB = 500
PORT0 = 8765


def _res(name, level, detail):
    return {"name": name, "level": level, "detail": detail}


def check_core_files(directory):
    """核心四件套存在性: 缺任何一个都算 fail"""
    required = {"tasks.json": os.path.isfile,
                "settings.json": os.path.isfile,
                "STATUS.json": os.path.isfile,
                "daily": os.path.isdir}
    missing = [n for n, probe in required.items()
               if not probe(os.path.join(directory, n))]
    if missing:
        return _res("核心文件", "fail", "缺失: " + ", ".join(missing))
    return _res("核心文件", "ok", "tasks/settings/STATUS/daily 齐备")


def _load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, str(e)[:60]


def check_json_integrity(directory):
    """JSON 可解析性: 核心三件损坏=fail; 台账/记忆档案缺失=warn(可再生)"""
    out = []
    for name in ("tasks.json", "settings.json", "STATUS.json"):
        data, err = _load_json(os.path.join(directory, name))
        if err == "missing":
            out.append(_res(name, "fail", "文件缺失"))
        elif err:
            out.append(_res(name, "fail", "解析失败: " + err))
        else:
            out.append(_res(name, "ok", "可解析"))
    for opt in ("daily/knowledge.json", "daily/analysis.json"):
        p = os.path.join(directory, *opt.split("/"))
        if not os.path.exists(p):
            out.append(_res(opt, "warn", "尚未生成(首次使用属正常)"))
            continue
        data, err = _load_json(p)
        out.append(_res(opt, "ok" if err is None else "fail",
                        "可解析" if err is None else "解析失败: " + err))
    return out


def check_disk(directory, min_free_mb=MIN_FREE_MB, usage=None):
    """磁盘剩余空间; usage 可注入(types.SimpleNamespace(free=字节))"""
    usage = usage or (lambda p: __import__("shutil").disk_usage(p))
    free_mb = usage(str(directory)).free / 1048576.0
    if free_mb >= min_free_mb:
        return _res("磁盘空间", "ok", "剩余 %.0f MB" % free_mb)
    return _res("磁盘空间", "fail",
                "剩余 %.0f MB, 低于阈值 %d MB" % (free_mb, min_free_mb))


def _default_connector(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def check_port(port=PORT0, connector=None):
    """端口探测纯提示: 有实例在跑=运行中; 空闲=未启动(都不是错误)"""
    conn = connector or _default_connector
    occupied = bool(conn(port))
    detail = ("运行中(端口 %d)" % port) if occupied else ("空闲(端口 %d)" % port)
    return _res("服务端口", "info", detail)


def exit_code_for(results):
    """退出码只由硬失败(fail)决定; warn/info 一律放行"""
    return 1 if any(r.get("level") == "fail" for r in results) else 0


def main():
    base = paths.app_base()
    results = []
    results.append(check_core_files(base))
    results.extend(check_json_integrity(base))
    results.append(check_disk(base))
    results.append(check_port())
    bdir = os.path.join(base, "backup")
    if os.path.isdir(bdir) and any(f.endswith(".zip") for f in os.listdir(bdir)):
        results.append(_res("备份状态", "ok", "backup\\ 已有自动备份"))
    else:
        results.append(_res("备份状态", "warn",
                            "还没有任何备份——下次启动会自动生成"))

    print("=== LearningHub 自检 · %s ===" % base)
    icons = {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "ℹ️"}
    for r in results:
        print("%s %-12s %s" % (icons.get(r["level"], "•"), r["name"], r["detail"]))
    code = exit_code_for(results)
    print("---")
    print("总体:", "存在问题，请按 ❌/⚠️ 提示处理" if code else "健康")
    return code


if __name__ == "__main__":
    sys.exit(main())
