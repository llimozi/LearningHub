# -*- coding: utf-8 -*-
r"""paths.py —— 应用根目录解析 (v1.4 · 纯标准库)

为什么需要它: PyInstaller --onefile 运行时, __file__ 指向临时解包目录
(%TEMP%\_MEIxxxx), 若入口脚本继续用 __file__ 当数据目录, 用户的学习数据
会被写进临时文件夹并随进程退出消失——这是打包分发最容易踩的致命坑。

契约:
  源码态  python resident.py / build_dashboard.py
          → app_base() = 本模块所在目录(即项目根目录)
  打包态  LearningHub.exe(由 resident.py 打包)
          → app_base() = exe 所在目录(用户桌面/安装处), 数据与 exe 同侧

公开 API:
  app_base(is_frozen=None, exe_path=None) -> str
      # 参数供测试注入; 生产直接调用自动读 sys.frozen / sys.executable

接入点: 仅 build_dashboard.py 与 resident.py 的 BASE 常量改走本函数;
其余模块(settings/backup/search/…)全部以 learning_dir 参数接收目录, 无需改动。
"""
import os
import sys


def app_base(is_frozen=None, exe_path=None):
    """返回应用根目录。is_frozen/exe_path 可注入以便测试双模式。"""
    frozen = getattr(sys, "frozen", False) if is_frozen is None else is_frozen
    if frozen:
        exe = exe_path or getattr(sys, "executable", "")
        return os.path.dirname(os.path.abspath(exe))
    return os.path.dirname(os.path.abspath(__file__))
