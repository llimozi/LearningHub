# -*- coding: utf-8 -*-
r"""transfer.py —— 手动导入 / 导出 (v1.1 · 纯标准库)

导出 export_bundle:
  任务库 + 知识点台账 + 概念网络(+知识点记忆档案) -> 单个 JSON 对象,
  由前端触发浏览器下载或调用方自行落盘。缺哪个文件就少哪段, 不炸不虚构。

导入 import_bundle 的铁律顺序:
  1.【先校验】格式不对(kind 不认识/data 缺失)直接拒收——此时一个字节都不写、连备份都不做;
  2.【再备份】校验通过后无条件 backup_now 留退路(备份里是导入前的旧状态);
  3.【后合并】同 id 覆盖、新 id 追加:
       tasks   按 日期桶+任务id 合并; history 按日期合并并裁剪回30天;
       notes   台账按日期合并;      同日整条覆盖;
       knowledge 记忆档案按概念名合并;
       graph   若台账有更新则按合并后的台账【重建】(杜绝新台账配旧图谱的错位),
               台账缺席时才整体采用包内图谱。
  坏段落(类型不对)跳过并记入 warnings, 不拖垮其余段落。

公开 API:
  export_bundle(learning_dir, now=None)          -> dict
  import_bundle(learning_dir, bundle, now=None)  -> {ok, backup, sections, warnings[, err]}
"""
import os
import json
import logging
import datetime
import shutil

import backup as backup_mod

APP_TAG = "learning-hub"
KIND = "full-export"
VERSION = 1
EXPORT_SECTIONS = ("tasks.json", "daily/analysis.json",
                   "daily/graph.json", "daily/knowledge.json")
HISTORY_KEEP = 30                                   # 与 planner.HISTORY_KEEP 口径一致


def _sec_path(learning_dir, arc):
    """'daily/analysis.json' -> 绝对路径(zip 弧名统一正斜杠)"""
    return os.path.join(learning_dir, *arc.split("/"))


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _write_json(path, obj):
    """原子写入: 先写 .tmp 再 os.replace, 防止写一半断电损坏。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except (OSError, TypeError) as e:
        # 导入包已通过前置备份；落盘失败必须中断，避免留下“看似成功”的半包。
        logging.error("Import data write failed in _write_json: %s", e,
                      exc_info=True)
        raise


# ---------------- 导出 ----------------
def export_bundle(learning_dir, now=None):
    """把核心数据段打成单个可移植 JSON 对象"""
    data = {}
    for arc in EXPORT_SECTIONS:
        p = _sec_path(learning_dir, arc)
        if os.path.isfile(p):
            content = _load(p, None)
            if content is not None:
                data[arc] = content
    return {
        "app": APP_TAG,
        "kind": KIND,
        "version": VERSION,
        "exported_at": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
        "data": data,
    }


# ---------------- 合并原语 ----------------
def _merge_tasks(cur, inc):
    """任务库合并(就地改 cur): 日期桶内按 id 覆盖/追加; history 按日期合并+裁剪;
    fatigue 只在当前缺失时采纳; log 按内容去重追加。返回计数。"""
    added = overwritten = 0
    days_cur = cur.setdefault("days", {})
    for date, bucket in (inc.get("days") or {}).items():
        if not date or not isinstance(bucket, list):
            continue
        target = days_cur.setdefault(date, [])
        index = {}
        for i, t in enumerate(target):
            if isinstance(t, dict) and t.get("id"):
                index[t["id"]] = i
        for t in bucket:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if tid and tid in index:
                target[index[tid]] = t                  # 同 id: 整条覆盖
                overwritten += 1
            else:
                if tid:
                    index[tid] = len(target)
                target.append(t)                        # 新 id: 追加
                added += 1

    hist_merged = 0
    hist_cur = cur.setdefault("history", [])
    hindex = {h.get("date"): i for i, h in enumerate(hist_cur) if isinstance(h, dict)}
    for h in (inc.get("history") or []):
        if not isinstance(h, dict) or not h.get("date"):
            continue
        d = h["date"]
        if d in hindex:
            hist_cur[hindex[d]] = h                     # 同日覆盖
        else:
            hindex[d] = len(hist_cur)
            hist_cur.append(h)
        hist_merged += 1
    hist_cur.sort(key=lambda x: x.get("date", "") if isinstance(x, dict) else "")
    del hist_cur[:-HISTORY_KEEP]

    if isinstance(inc.get("fatigue"), dict) and not cur.get("fatigue"):
        cur["fatigue"] = inc["fatigue"]

    log_cur = cur.setdefault("log", [])
    seen = set()
    for e in log_cur:
        try:
            seen.add(json.dumps(e, sort_keys=True, ensure_ascii=False))
        except (TypeError, ValueError):
            continue
    for e in (inc.get("log") or []):
        try:
            key = json.dumps(e, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        if key not in seen:
            log_cur.append(e)
            seen.add(key)
    return {"added": added, "overwritten": overwritten, "history_merged": hist_merged}


def _merge_keyed_section(cur, inc, container):
    """通用「同名覆盖、新名追加」: notes/dknowledge 这类 {容器键: {名字: 内容}} 结构"""
    added = overwritten = 0
    curn = cur.setdefault(container, {})
    incn = inc.get(container)
    if isinstance(incn, dict):
        for k, v in incn.items():
            if k in curn:
                overwritten += 1
            else:
                added += 1
            curn[k] = v
    return {"added": added, "overwritten": overwritten}


# ---------------- 导入 ----------------
def _fail(msg):
    return {"ok": False, "err": msg, "backup": None, "sections": {}, "warnings": []}


def import_bundle(learning_dir, bundle, now=None):
    """按「校验→备份→内存合并→原子落盘」铁律导入。
    任何情况下不满足前置条件都不落一笔; 落盘阶段任一失败则从文件级
    备份恢复所有已写的文件, 保证磁盘上不会出现新旧混合状态。
    """
    if not isinstance(bundle, dict):
        return _fail("导入内容须为 JSON 对象")
    if bundle.get("kind") != KIND:
        return _fail("不认识的导出格式(kind=%s), 已拒绝" % repr(bundle.get("kind")))
    data = bundle.get("data")
    if not isinstance(data, dict) or not data:
        return _fail("导出包没有数据段(data)")

    warnings = []
    sections = {}

    # —— 第一步: 备份(校验已过, 动笔之前先留退路) ——
    zip_path = backup_mod.backup_now(learning_dir, now=now)

    # —— 第二步: 纯内存合并(不碰磁盘) ——
    # 收集所有待写入内容: {绝对路径: 合并后的dict}
    writes = {}
    graph_mode = "skipped"

    try:
        # 任务库
        if "tasks.json" in data:
            inc = data["tasks.json"]
            if isinstance(inc, dict):
                p = _sec_path(learning_dir, "tasks.json")
                cur = _load(p, {})
                if not isinstance(cur, dict):
                    cur = {}
                sections["tasks"] = _merge_tasks(cur, inc)
                writes[p] = cur
            else:
                warnings.append("tasks.json 段不是对象, 已跳过")

        # 台账(合并到内存, 图谱稍后处理)
        analysis_written = False
        if "daily/analysis.json" in data:
            inc = data["daily/analysis.json"]
            if isinstance(inc, dict):
                p = _sec_path(learning_dir, "daily/analysis.json")
                cur = _load(p, {})
                if not isinstance(cur, dict):
                    cur = {}
                sections["notes"] = _merge_keyed_section(cur, inc, "notes")
                writes[p] = cur
                analysis_written = True
                graph_mode = "rebuilt"
            else:
                warnings.append("daily/analysis.json 段不是对象, 已跳过")
        elif "daily/graph.json" in data:
            inc = data["daily/graph.json"]
            if isinstance(inc, dict):
                p = _sec_path(learning_dir, "daily/graph.json")
                writes[p] = inc
                graph_mode = "from_bundle"
            else:
                warnings.append("daily/graph.json 段不是对象, 已跳过")
        sections["graph"] = graph_mode

        # 记忆档案
        if "daily/knowledge.json" in data:
            inc = data["daily/knowledge.json"]
            if isinstance(inc, dict):
                p = _sec_path(learning_dir, "daily/knowledge.json")
                cur = _load(p, {})
                if not isinstance(cur, dict):
                    cur = {}
                sections["knowledge"] = _merge_keyed_section(cur, inc, "knowledge")
                writes[p] = cur
            else:
                warnings.append("daily/knowledge.json 段不是对象, 已跳过")

        # 图谱重建(纯计算, 不落盘—写入阶段再存)
        if analysis_written:
            import graph as graph_mod
            graph_mod.build_graph(learning_dir, save=False)  # 仅计算, 写入阶段再存

    except Exception as e:
        logging.error("Import merge failed in import_bundle: %s", e, exc_info=True)
        return _fail("数据合并阶段失败: %s" % str(e)[:120])

    # —— 第三步: 原子落盘(全部合并成功才执行) ——
    # 先备份所有目标文件, 以便在任一写入失败时恢复
    file_backups = {}  # {原始路径: 备份路径}
    written_targets = []  # 已成功写入的目标路径(用于失败时恢复)

    try:
        # 3a: 为所有待写文件创建 .bak 备份
        for p in writes:
            if os.path.exists(p):
                bak = p + ".import_bak"
                shutil.copy2(p, bak)
                file_backups[p] = bak

        # 3b: 逐个原子写入
        for p, obj in writes.items():
            _write_json(p, obj)
            written_targets.append(p)

        # 3c: 图谱重建落盘(依赖已写入的 analysis.json)
        if analysis_written:
            import graph as graph_mod
            graph_mod.build_graph(learning_dir, save=True)

    except Exception as e:
        logging.error("Import write failed in import_bundle: %s", e, exc_info=True)
        # 恢复所有已写的文件到写入前状态
        for p in written_targets:
            bak = file_backups.get(p)
            if bak and os.path.exists(bak):
                try:
                    os.replace(bak, p)
                except Exception as restore_err:
                    logging.error("Import rollback failed for %s: %s", p, restore_err)
        # 清理备份文件
        for bak in file_backups.values():
            try:
                if os.path.exists(bak):
                    os.remove(bak)
            except Exception:
                pass
        return _fail("数据落盘阶段失败(已自动回滚): %s" % str(e)[:120])

    # 成功: 清理备份文件
    for bak in file_backups.values():
        try:
            if os.path.exists(bak):
                os.remove(bak)
        except Exception:
            pass

    return {"ok": True,
            "backup": os.path.basename(zip_path),
            "sections": sections,
            "warnings": warnings}
