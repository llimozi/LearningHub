# -*- coding: utf-8 -*-
r"""backup.py —— 数据自动备份 (v1.1 · zipfile 纯标准库)

规则:
  触发   启动时距上次成功备份 >= min_hours(默认24h) 才备; backup_now 可无条件手动备
  范围   tasks.json / settings.json / STATUS.json / stoplist.txt + daily\ 全部
         (reports 不入备份: 报告可随时再生, 不占保留额度)
  命名   backup\backup_YYYYMMDD_HHMM.zip
  轮转   只保留最近 KEEP_N=14 份(按文件名即时间戳排序), 超出删最旧
  记账   backup\meta.json 记 last_backup_ts / last_zip; 损坏按「从未备份」自愈

公开 API:
  backup_items(learning_dir)                  -> [(abs_path, arcname)]   # 存在才进清单
  make_backup_zip(learning_dir, now=None)     -> path                    # 只打包不记账
  backup_now(learning_dir, now=None)          -> path                    # 打包+记账+轮转
  maybe_backup(learning_dir, now=None, min_hours=24.0) -> path | None    # 到点才备
  read_meta(learning_dir)                     -> dict                    # 容错读取

本项目的数据文件散在 learning 根与 daily\ 下(没有单一 data\ 目录),
清单式设计让「备什么」集中一处, 未来加新数据文件只改 BACKUP_ITEMS。
"""
import os
import json
import logging
import zipfile
import datetime

BACKUP_DIR_NAME = "backup"
META_NAME = "meta.json"
KEEP_N = 14
STAMP_FMT = "%Y%m%d_%H%M"

# 根目录散文件 + 整个 daily\(含 analysis/graph/笔记)。reports 与代码、测试一律不备。
ROOT_ITEMS = ("tasks.json", "settings.json", "STATUS.json", "stoplist.txt")


def _backup_dir(learning_dir):
    return os.path.join(learning_dir, BACKUP_DIR_NAME)


def _meta_path(learning_dir):
    return os.path.join(_backup_dir(learning_dir), META_NAME)


def backup_items(learning_dir):
    """返回 [(绝对路径, zip内相对路径)]; 文件存在才进清单, 目录递归收 daily\\*"""
    items = []
    for name in ROOT_ITEMS:
        p = os.path.join(learning_dir, name)
        if os.path.isfile(p):
            items.append((p, name))
    daily = os.path.join(learning_dir, "daily")
    if os.path.isdir(daily):
        for fn in sorted(os.listdir(daily)):
            p = os.path.join(daily, fn)
            if os.path.isfile(p):
                items.append((p, "daily/" + fn))        # zip 内统一正斜杠, 跨平台解包友好
    return items


def make_backup_zip(learning_dir, now=None):
    """打包当前数据为 backup_YYYYMMDD_HHMM.zip, 返回路径; 空数据也产出合法空 zip"""
    now = now or datetime.datetime.now()
    bdir = _backup_dir(learning_dir)
    stamp = now.strftime(STAMP_FMT)
    path = os.path.join(bdir, "backup_" + stamp + ".zip")
    try:
        os.makedirs(bdir, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, arc in backup_items(learning_dir):
                try:
                    zf.write(src, arc)
                except OSError:
                    continue                            # 单文件被占用等: 跳过不炸整包
    except (OSError, TypeError) as e:
        # 备份是数据退路, 失败必须留现场并让调用方感知。
        logging.error("Backup write failed in make_backup_zip: %s", e, exc_info=True)
        raise
    return path


def read_meta(learning_dir):
    """容错读 meta; 缺失/损坏返回 {}(调用方视为从未备份, 自愈重备)"""
    try:
        with open(_meta_path(learning_dir), encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_meta(learning_dir, meta):
    """原子写 meta(同 settings 的 tmp+replace 手法)"""
    p = _meta_path(learning_dir)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8-sig") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except (OSError, TypeError) as e:
        logging.error("Backup metadata write failed in _write_meta: %s", e,
                      exc_info=True)
        raise


def _prune(learning_dir, keep=KEEP_N):
    """按文件名(即时间戳)降序保留最近 keep 份, 其余删除。只动自己的 backup_*.zip。"""
    bdir = _backup_dir(learning_dir)
    zips = sorted((n for n in os.listdir(bdir)
                   if n.startswith("backup_") and n.endswith(".zip")),
                  reverse=True)
    for old in zips[keep:]:
        try:
            os.remove(os.path.join(bdir, old))
        except OSError:
            pass                                        # 删不掉(被占用): 留给下轮


def backup_now(learning_dir, now=None):
    """无条件备份 + 写 meta + 轮转。返回 zip 路径。"""
    path = make_backup_zip(learning_dir, now=now)
    _write_meta(learning_dir, {
        "last_backup_ts": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
        "last_zip": os.path.basename(path),
    })
    _prune(learning_dir)
    return path


def maybe_backup(learning_dir, now=None, min_hours=24.0):
    """启动入口: 距上次成功备份 >= min_hours(或从未备过/meta损坏)才执行 backup_now;
    未到点返回 None 且零写入——空闲启动零成本。"""
    meta = read_meta(learning_dir)
    last = meta.get("last_backup_ts")
    due = True
    if last:
        try:
            age = (now or datetime.datetime.now()) - datetime.datetime.fromisoformat(str(last))
            due = age.total_seconds() >= min_hours * 3600.0
        except ValueError:
            due = True                                  # 时间戳解析不了: 当作该备了
    if not due:
        return None
    return backup_now(learning_dir, now=now)
