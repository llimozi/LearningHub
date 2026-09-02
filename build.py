# -*- coding: utf-8 -*-
r"""build.py —— 一键打包 LearningHub.exe (v1.4 · 纯标准库编排)

定位: PyInstaller 是**仅开发期**的打包工具(运行时零第三方依赖的铁律不变);
本脚本只是把「生成图标 → 收集资源 → 组装参数 → 调用 PyInstaller」串成一键。

用法:
  python build.py            # 完整打包, 产物 dist\LearningHub.exe
  python build.py --check    # 只校验环境与清单, 不实际打包

资源适配说明(如实记录): 原规格写 data/ templates/ static/, 本项目实际形态是
「根目录散文件 + daily\ 数据目录 + editor.html 页面」。DATA_FILES 即随身资源的
唯一清单——运行时数据(tasks/daily/settings…)由首次运行向导在 exe 旁生成,
**不打进包里**(每个用户的数据必须独立)。

公开 API(供测试):
  DATA_FILES                       -> [(相对路径, 包内弧)]
  pyinstaller_args(icon, name, entry) -> [参数列表]   # 入口 resident.py 收口
  check_environment(finder=None)   -> (ok, 消息)      # 探测 PyInstaller 可用性
  ensure_icon(path)                -> 图标路径        # 复用 tray 的手写字节生成
"""
import os
import sys
import subprocess

import paths
import tray

APP_NAME = "LearningHub"
ENTRY = "resident.py"
ICON_PATH = os.path.join("assets", "learninghub.ico")

# 随身运行资源: (项目内路径, 包内弧)。editor.html 是 /editor 的载体;
# stoplist.txt 作为 analyzer 初始停用词模板随包分发。
DATA_FILES = [
    ("editor.html", "."),
    ("stoplist.txt", "."),
]

REQUIRED_TOOLS = ("pyinstaller",)


def pyinstaller_args(icon=ICON_PATH, name=APP_NAME, entry=ENTRY):
    """组装 PyInstaller 参数。顺序稳定便于测试; 入口脚本必须最后收口。"""
    args = ["--noconfirm", "--clean", "--onefile", "--noconsole"]
    args.append("--icon=" + icon)
    args.append("--name=" + name)
    for src, arc in DATA_FILES:
        sep = ";" if os.name == "nt" else ":"
        args.append("--add-data=%s%s%s" % (src, sep, arc))
    args.append(entry)
    return args


def check_environment(finder=None):
    """探测 PyInstaller 是否可用。finder 可注入(pytest 无网络环境友好)。"""
    finder = finder or _default_finder
    for tool in REQUIRED_TOOLS:
        if finder(tool):
            return True, "已找到 %s: %s" % (tool, finder(tool))
    return False, (
        "未找到 PyInstaller。它是【仅开发期】工具, 不影响程序运行时的零依赖。"
        "安装命令(国内建议加清华镜像):\n"
        "  pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
        "安装完成后重新运行本脚本。")


def _default_finder(tool):
    import shutil
    found = shutil.which(tool)
    if found:
        return found
    try:                                                     # 兼容 python -m PyInstaller 安装方式
        r = subprocess.run([sys.executable, "-m", tool, "--version"],
                           capture_output=True, timeout=30)
        if r.returncode == 0:
            return "%s -m %s" % (sys.executable, tool)
    except Exception:
        pass
    return None


def ensure_icon(path=ICON_PATH):
    """用 tray 的纯字节 ICO 生成器产出应用图标; 已存在则复用不重写"""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(tray.make_ico_bytes((16, 32, 48)))
    return path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base = paths.app_base()
    ok, msg = check_environment()
    print("[env]", msg)
    if not ok:
        return 1
    icon = ensure_icon(os.path.join(base, ICON_PATH))
    print("[icon]", icon)

    args = pyinstaller_args(icon=os.path.join(base, ICON_PATH),
                            name=APP_NAME, entry=ENTRY)
    if "--check" in argv:
        print("[check-only] 将执行:", " ".join(args))
        return 0
    entry_path = os.path.join(base, ENTRY)
    if not os.path.exists(entry_path):
        print("[ERR] 找不到入口脚本", entry_path)
        return 1
    print("[build]", " ".join(args))
    r = subprocess.run([sys.executable, "-m", "PyInstaller"] + args,
                       cwd=base)
    dist_exe = os.path.join(base, "dist", APP_NAME + ".exe")
    if r.returncode == 0 and os.path.exists(dist_exe):
        size_mb = os.path.getsize(dist_exe) / 1048576.0
        print("[OK] 产物: %s (%.1f MB)" % (dist_exe, size_mb))
        print("[hint] 把 exe 单文件拷到任意目录即可使用; 数据会生成在同目录")
        return 0
    print("[ERR] 打包未成功, 请查看上方 PyInstaller 输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
