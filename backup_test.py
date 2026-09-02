# -*- coding: utf-8 -*-
"""backup_test.py —— 自动备份单元测试 (v1.1 · 纯标准库)
跑法A: pytest backup_test.py      跑法B: python backup_test.py (零依赖runner)
覆盖: 备份清单覆盖面 / zip 内容与命名格式 / meta 记账 / 24小时窗口判定 /
      轮转只留最近14份 / 缺文件容错 / meta 损坏自愈。全部用临时目录+固定时钟。
"""
import datetime
import json
import os
import shutil
import tempfile
import zipfile

from backup import (backup_items, make_backup_zip, backup_now,
                    maybe_backup, read_meta, BACKUP_DIR_NAME, KEEP_N)

NOW = datetime.datetime(2099, 6, 1, 12, 0, 0)


def _mk_learning_dir():
    """标准学习目录形状: 根上三个 json + daily/ 两篇笔记"""
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "tasks.json"), "w", encoding="utf-8") as f:
        f.write('{"days": {}, "history": []}')
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"theme": "dark"}')
    with open(os.path.join(tmp, "STATUS.json"), "w", encoding="utf-8") as f:
        f.write('{"streak": 3}')
    os.makedirs(os.path.join(tmp, "daily"))
    with open(os.path.join(tmp, "daily", "2099-05-31.md"), "w", encoding="utf-8") as f:
        f.write("# 五月的笔记\n内容")
    with open(os.path.join(tmp, "daily", "analysis.json"), "w", encoding="utf-8") as f:
        f.write('{"notes": {}}')
    return tmp


def _zips(d):
    return sorted(n for n in os.listdir(os.path.join(d, BACKUP_DIR_NAME))
                  if n.endswith(".zip"))


# ---------------- 清单 ----------------
def test_backup_items_cover_core_and_daily():
    d = _mk_learning_dir()
    try:
        items = dict((arc, src) for src, arc in backup_items(d))
        assert "tasks.json" in items and "settings.json" in items, items.keys()
        assert "STATUS.json" in items
        assert "daily/2099-05-31.md" in items, items.keys()
        assert "daily/analysis.json" in items
        for arc, src in items.items():
            assert os.path.exists(src), arc                 # 清单里不许有不存在的路径
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_backup_items_skip_missing_files():
    d = tempfile.mkdtemp()
    try:
        arcs = [arc for _, arc in backup_items(d)]
        assert "tasks.json" not in arcs                     # 空目录: 有啥备啥, 不炸不虚构
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 打包 ----------------
def test_make_backup_zip_name_format_and_content():
    d = _mk_learning_dir()
    try:
        p = make_backup_zip(d, now=NOW)
        name = os.path.basename(p)
        import re
        assert re.match(r"^backup_\d{8}_\d{4}\.zip$", name), name
        with zipfile.ZipFile(p) as zf:
            names = zf.namelist()
            assert "daily/2099-05-31.md" in names
            body = zf.read("settings.json").decode("utf-8")
            assert '"theme"' in body                        # 内容原样进包
            bad = zf.testzip()
            assert bad is None, bad                         # CRC 校验全过
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_backup_now_writes_meta_and_returns_path():
    d = _mk_learning_dir()
    try:
        p = backup_now(d, now=NOW)
        assert os.path.exists(p)
        meta = read_meta(d)
        assert meta["last_zip"] == os.path.basename(p), meta
        ts = datetime.datetime.fromisoformat(meta["last_backup_ts"])
        assert ts == NOW, meta
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_backup_empty_dir_still_creates_zip():
    d = tempfile.mkdtemp()
    try:
        p = backup_now(d, now=NOW)                          # 啥都没有也不许炸
        assert os.path.exists(p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 24 小时窗口 ----------------
def test_maybe_backup_first_run_backs_up_immediately():
    d = _mk_learning_dir()
    try:
        p = maybe_backup(d, now=NOW, min_hours=24.0)
        assert p is not None, "从未备份过: 第一次启动必须立刻备"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_maybe_backup_skips_within_window():
    d = _mk_learning_dir()
    try:
        backup_now(d, now=NOW - datetime.timedelta(hours=1))
        n_before = len(_zips(d))
        p = maybe_backup(d, now=NOW, min_hours=24.0)
        assert p is None, "刚备过 1 小时不应再备"
        assert len(_zips(d)) == n_before
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_maybe_backup_fires_after_window():
    d = _mk_learning_dir()
    try:
        backup_now(d, now=NOW - datetime.timedelta(hours=25))
        p = maybe_backup(d, now=NOW, min_hours=24.0)
        assert p is not None, "超过 24h 必须再备"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_maybe_backup_self_heals_on_corrupted_meta():
    d = _mk_learning_dir()
    try:
        os.makedirs(os.path.join(d, BACKUP_DIR_NAME))
        with open(os.path.join(d, BACKUP_DIR_NAME, "meta.json"), "w",
                  encoding="utf-8") as f:
            f.write("{oops")                                # 半截 JSON
        p = maybe_backup(d, now=NOW, min_hours=24.0)
        assert p is not None, "meta 损坏按『从未备份』处理, 自愈重备"
        assert read_meta(d)["last_backup_ts"]               # 且写回干净 meta
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 轮转 ----------------
def test_prune_keeps_only_recent_fourteen():
    d = _mk_learning_dir()
    try:
        bdir = os.path.join(d, BACKUP_DIR_NAME)
        os.makedirs(bdir)
        # 伪造 18 份历史备份(时间戳递增命名, 内容随意)
        for day in range(1, 19):
            with open(os.path.join(bdir, "backup_209905%02d_1200.zip" % day),
                      "w", encoding="utf-8") as f:
                f.write("fake")
        backup_now(d, now=NOW)                              # 第 19 份进场触发轮转
        zips = _zips(d)
        assert len(zips) <= KEEP_N, (len(zips), zips)
        assert "backup_20990601_1200.zip" in zips           # 最新的一份必须在
        assert "backup_20990501_1200.zip" not in zips       # 最老的必须被清
        meta_files = [n for n in os.listdir(bdir) if not n.endswith(".zip")]
        assert all(not n.endswith(".zip") for n in meta_files)
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
