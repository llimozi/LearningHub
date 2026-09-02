# -*- coding: utf-8 -*-
"""api.py —— API 处理器（原 build_dashboard.py C 类, Phase 2.4 迁移）。

依赖: services / data / utils / config + 外部业务模块。
注意: 统一通过模块对象动态访问 config/data, 便于测试 patch 数据隔离。
"""
import json
import logging
import os
import re
import datetime

import analytics
import backup
import firstrun
import forgetting
import graph
import helpcenter
import mastery
import reportio
import search
import settings
import theme
import transfer

from _app import config, data
from _app.services import _expire_fatigue_meta


def api_daily_focus():
    """GET /api/daily-focus: 五级优先级的『今日焦点』一句话导航。
    为什么放 build_dashboard 而非 analytics: 需要减负 meta/TODAY 桶/到期队列等
    路由层状态, 属于展示编排; analytics 保持纯计算。CLI 取自缓存, 几乎零成本。"""
    # 统一读取一次, 避免函数内多次重复 I/O (tasks.json × 4 + knowledge.json × 3)
    st = _expire_fatigue_meta(data.load_tasks())
    a = analytics.get_analytics(config.BASE)
    return _focus_impl(st, a)


def _focus_impl(st, a):
    """实现拆分: 接收已加载的数据, 纯计算无 I/O。"""
    fo = (st.get("meta") or {}).get("fatigue_override") or {}
    if fo.get("active"):
        return {"ok": True, "icon": "🛡️", "urgency": "mid",
                "text": "减负中——今天只保 P1 高优, 其余交给明天", "link_hash": "#pnl-tasks"}
    stb = a.get("stability", {})
    weak_tag = stb.get("weakest_tag")
    if weak_tag and weak_tag != "未分类":
        names = set()
        for row in stb.get("rows", []):
            if row["tag"] == weak_tag:
                names = set(c["name"] for c in row.get("concepts", []))
        hit = [c["concept"] for c in forgetting.due_cards(config.BASE) if c["concept"] in names]
        if hit:
            first = str(hit[0])[:18]
            return {"ok": True, "icon": "🧠", "urgency": "high",
                    "text": "先刷 #" + weak_tag + " 的 " + str(len(hit)) + " 张到期卡(" + first + "…)",
                    "link_hash": "#pnl-review"}
    bucket = st.get("days", {}).get(config.TODAY, []) or []
    p1 = [t for t in bucket if int(t.get("priority", 2)) == 1 and not t.get("done")]
    if p1:
        txt = "攻克「" + str(p1[0].get("text", ""))[:22] + "」"
        em = p1[0].get("est_minutes")
        if em:
            txt += "(⏱" + str(em) + "m)"
        return {"ok": True, "icon": "🎯", "urgency": "high", "text": txt, "link_hash": "#pnl-tasks"}
    cli_idx = (a.get("cli") or {}).get("index")
    if isinstance(cli_idx, int) and cli_idx > 80:
        return {"ok": True, "icon": "🔥", "urgency": "high",
                "text": "今天负荷偏重——只做核心任务, 别加新内容", "link_hash": "#pnl-tasks"}
    if bucket:
        undone = sum(1 for t in bucket if not t.get("done"))
        return {"ok": True, "icon": "📋", "urgency": "mid",
                "text": "按优先级从上往下清, 还剩 " + str(undone) + " 条", "link_hash": "#pnl-tasks"}
    return {"ok": True, "icon": "🌱", "urgency": "low",
            "text": "今天还没有任务——去 daily 写一条开始吧", "link_hash": "#pnl-tasks"}


# ---------------- v1.0 设置接口本体(HTTP 层薄封装, 逻辑可单测) ----------------
def api_get_settings(learning_dir=None, reg=None):
    """GET /api/settings: 偏好设置 + 注册表实际登记情况(autostart_registered)"""
    ld = learning_dir or config.BASE
    return {"ok": True, "settings": settings.load_settings(ld),
            "autostart_registered": settings.get_autostart(reg)}

def api_post_settings(patch, learning_dir=None, reg=None, exe=None):
    """POST /api/settings: 深合并补丁并落盘; autostart 布尔翻转时同步写/删注册表。
    注册表失败不回滚偏好(autostart_error 字段上报, 前端提示)——偏好与系统状态解耦。"""
    ld = learning_dir or config.BASE
    if not isinstance(patch, dict):
        return {"ok": False, "err": "补丁须为 JSON 对象"}
    cur = settings.load_settings(ld)
    merged = settings.deep_merge(cur, patch)
    out = {"ok": True, "settings": merged,
           "autostart_registered": None, "autostart_error": None}
    want = patch.get("autostart")
    if isinstance(want, bool) and want != bool(cur.get("autostart")):
        try:
            out["autostart_registered"] = settings.set_autostart(
                want, learning_dir=ld, reg=reg, exe=exe)
        except Exception as e:                          # 权限/企业策略等, 不炸接口
            out["autostart_error"] = str(e)[:120]
    settings.save_settings(ld, merged)
    return out

# ---------------- v1.1 数据闭环接口本体(逻辑可测, HTTP 薄封装) ----------------
def api_patch_done_at(req, st):
    """POST /api/tasks/patch-done-at {ids:[...], done_at:"YYYY-MM-DDTHH:MM"}
    v1.7 模块B: 为已完成但缺时刻的任务补录 done_at(只认 done=true, 未完成跳过并回报)。
    为什么接收 st: do_POST 顶部已做过次日过期检查, 复用同一份状态避免二次读盘竞态。
    为什么立即失效缓存: 补录时刻会改变专注时段分布, 必须当次刷新即可见。"""
    ids = req.get("ids") if isinstance(req.get("ids"), list) else []
    ts = str(req.get("done_at", "")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", ts):
        return {"ok": False, "err": "时间格式须为 YYYY-MM-DDTHH:MM"}
    if ts.count(":") == 1:
        ts += ":00"
    try:
        datetime.datetime.fromisoformat(ts)
    except ValueError:
        return {"ok": False, "err": "不是合法的日期时间"}
    idset = set(str(i) for i in ids)
    actual = req.get("actual_minutes")                     # v1.8 A3: 可选实际耗时(非必填)
    if actual is not None:
        try:
            actual = max(1, min(600, int(actual)))
        except Exception:
            actual = None
    patched, skipped = [], []
    for bucket in st.get("days", {}).values():
        for t in bucket:
            tid2 = t.get("id")
            if tid2 in idset:
                if t.get("done"):
                    t["done_at"] = ts
                    if actual is not None:
                        t["actual_minutes"] = actual       # 预留字段: 时间预算对比的数据源
                    patched.append(tid2)
                else:
                    skipped.append(tid2)
    if patched:
        data.save_tasks(st)
        try:
            analytics.invalidate_cache(config.BASE)
        except Exception:
            pass
    return {"ok": True, "patched": patched, "skipped": skipped}


def api_snooze_all(req):
    """POST /api/review/snooze-all {days:3}: CLI 减负模式配套——今日到期/逾期卡统一软推迟。
    为什么用软字段 snooze_until 而不改 SM-2 间隔: 不污染 review_count/ease 真实历史,
    到点真复习(mark_reviewed 已加解除逻辑)自动清推迟, 减负结束后节奏自然回归。"""
    try:
        days = max(1, min(7, int(req.get("days", 3))))
    except Exception:
        days = 3
    today = datetime.date.today()
    data = forgetting.load_knowledge(config.BASE)
    snoozed = []
    for c0 in forgetting.due_cards(config.BASE):
        rec = data["knowledge"].get(c0.get("concept"))
        if rec is None:
            continue
        rec["snooze_until"] = (today + datetime.timedelta(days=days)).isoformat()
        snoozed.append(c0.get("concept"))
    if snoozed:
        forgetting.save_knowledge(config.BASE, data)
        try:
            analytics.invalidate_cache(config.BASE)
        except Exception:
            pass
    return {"ok": True, "days": days, "snoozed": snoozed}


def api_fatigue_state():
    """GET /api/fatigue: 当天减负开关状态(_expire_fatigue_meta 保证跨天已清)。"""
    st = _expire_fatigue_meta(data.load_tasks())
    fo = (st.get("meta") or {}).get("fatigue_override") or {}
    return {"ok": True, "active": bool(fo.get("active"))}


def api_fatigue_toggle(req):
    """POST /api/fatigue {active:bool}: 记录当天减负选择并落盘 tasks.json meta。
    关闭也留痕(active=false): 否则 CLI>80 时开关条每次刷新都反复弹出骚扰用户;
    整条记录次日由 _expire_fatigue_meta 自动清除, 全程零定时任务。"""
    active = bool(req.get("active"))
    st = _expire_fatigue_meta(data.load_tasks())
    meta = st.setdefault("meta", {})
    meta["fatigue_override"] = {"active": active, "date": config.TODAY}
    data.save_tasks(st)
    return {"ok": True, "active": active, "date": config.TODAY}


def _load_operations():
    """读取操作审计日志；缺失或坏件都回退为空日志。"""
    try:
        with open(config.OPS_FILE, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"ops": []}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"ops": []}


def log_op(op):
    """v1.9 C4: 操作审计+撤销依据(服务端回滚需要 before 快照)。上限50条防膨胀。"""
    data = _load_operations()
    try:
        ops = data.get("ops", [])
        if not isinstance(ops, list):
            ops = []
            data["ops"] = ops
        ops.append(op)
        del ops[:-50]
        with open(config.OPS_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(data, f, ensure_ascii=False)
    except (OSError, TypeError, ValueError):
        pass


def api_undo():
    """POST /api/undo: 回滚最近一条未撤销操作(基于 log 中的 before 快照)。"""
    ops = _load_operations().get("ops", [])
    if not isinstance(ops, list):
        ops = []
    target = None
    for op in reversed(ops):
        if not op.get("undone"):
            target = op
            break
    if not target:
        return {"ok": False, "err": "没有可撤销的操作"}
    st = data.load_tasks()
    u = target.get("undo", {})
    ds = u.get("date", config.TODAY)
    bucket = st.setdefault("days", {}).setdefault(ds, [])
    typ = target["type"]
    if typ in ("toggle", "batch_done"):
        for t in bucket:
            tid2 = str(t.get("id"))
            if tid2 in u.get("before", {}):
                was = u["before"][tid2]
                t["done"] = was
                if not was:
                    t.pop("done_at", None)
    elif typ == "batch_priority":
        for t in bucket:
            tid2 = str(t.get("id"))
            if tid2 in u.get("before", {}):
                t["priority"] = int(u["before"][tid2])
    elif typ == "batch_delete":
        have = set(str(t.get("id")) for t in bucket)
        for snap in u.get("snapshot", []):
            if str(snap.get("id")) not in have:
                bucket.append(snap)
    elif typ == "batch_snooze":
        nxt = u.get("to_date")
        nbucket = st["days"].get(nxt, [])
        want_ids = set(u.get("ids", []))
        moved = [t for t in nbucket if str(t.get("id")) in want_ids]
        st["days"][nxt] = [t for t in nbucket if str(t.get("id")) not in want_ids]
        for t in moved:
            t["carried"] = u.get("was_carried", False)
        bucket[:0] = moved
    elif typ == "quick_create":
        st["days"][ds] = [t for t in bucket if str(t.get("id")) != str(u.get("task_id"))]
    else:
        return {"ok": False, "err": "该操作类型不支持撤销"}
    data.save_tasks(st)
    target["undone"] = True
    try:
        allops = _load_operations()
        for op2 in allops.get("ops", []):
            if op2.get("id") == target.get("id"):
                op2["undone"] = True
        with open(config.OPS_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(allops, f, ensure_ascii=False)
    except (OSError, TypeError, ValueError):
        pass
    try:
        analytics.invalidate_cache(config.BASE)
    except Exception:
        pass
    return {"ok": True, "type": typ, "label": target.get("label", typ)}



def api_analytics():
    """GET /api/analytics: 学习洞察三指标(CLI/知识稳固度/专注时段), mtime+TTL 缓存"""
    try:
        return {"ok": True, "analytics": analytics.get_analytics(config.BASE)}
    except Exception as e:
        logging.error("Boundary error in api_analytics: %s", e, exc_info=True)
        return {"ok": False, "err": str(e)[:120]}


def api_due_reviews(learning_dir=None):
    """GET /api/due_reviews: 同步记忆档案 -> 今日待复习队列(优先于新任务)"""
    ld = learning_dir or config.BASE
    try:
        forgetting.sync_from_analysis(ld, normalize=True)   # Phase D-D: 生产启用归一化
        cards = forgetting.due_cards(ld, top_n=12)
    except Exception as e:
        logging.error("Boundary error in api_due_reviews: %s", e, exc_info=True)
        return {"ok": False, "err": str(e)[:120], "cards": [], "count": 0}
    return {"ok": True, "count": len(cards), "cards": cards}

def api_mark_reviewed(concept, learning_dir=None, quality=None):
    """POST /api/mark_reviewed {concept, quality?}: 打卡一次复习(v1.9 支持快捷评分 1~5)"""
    concept = str(concept or "").strip()
    if not concept:
        return {"ok": False, "err": "缺少 concept"}
    q = None
    if quality is not None:
        try:
            q = max(0, min(5, int(quality)))
        except Exception:
            q = None
    return {"ok": forgetting.mark_reviewed(learning_dir or config.BASE, concept, quality=q or 4)}

def api_retention(learning_dir=None):
    """GET /api/retention: 记忆衰减卡片数据(保持率升序)"""
    ld = learning_dir or config.BASE
    try:
        forgetting.sync_from_analysis(ld, normalize=True)   # Phase D-D: 生产启用归一化
        rows = forgetting.decay_rows(ld, top_n=20)
    except Exception as e:
        logging.error("Boundary error in api_retention: %s", e, exc_info=True)
        return {"ok": False, "err": str(e)[:120], "rows": []}
    return {"ok": True, "rows": rows}

def api_export(learning_dir=None):
    """GET /api/export: 任务库+台账+图谱(+记忆档案) 单文件 JSON 包"""
    return transfer.export_bundle(learning_dir or config.BASE)

def api_import(bundle, learning_dir=None):
    """POST /api/import: 校验->自动备份->合并; 完事后图谱与台账双保险对齐"""
    out = transfer.import_bundle(learning_dir or config.BASE, bundle)
    if out.get("ok"):
        try:
            graph.build_graph(learning_dir or config.BASE, save=True)
        except Exception:
            pass                                        # transfer 内部已重建过, 这里兜底
    return out

def api_backup_now(learning_dir=None):
    p = backup.backup_now(learning_dir or config.BASE)
    return {"ok": True, "name": os.path.basename(p)}

def api_list_reports(learning_dir=None):
    return {"ok": True, "reports": reportio.list_reports(learning_dir or config.BASE)}

def api_read_report(name, learning_dir=None):
    body = reportio.read_report(learning_dir or config.BASE, str(name or ""))
    if body is None:
        return {"ok": False, "err": "报告不存在或名字不合法"}
    return {"ok": True, "name": os.path.basename(str(name)), "markdown": body}

# ---------------- v1.2 智能增强接口本体 ----------------
def api_mastery(learning_dir=None):
    """GET /api/mastery: 全概念掌握分 + 重点攻克队列(写回幂等)"""
    ld = learning_dir or config.BASE
    try:
        scores = mastery.update_mastery_scores(ld)
        weak = mastery.weak_concepts(ld, top_n=5)
    except Exception as e:
        logging.error("Boundary error in api_mastery: %s", e, exc_info=True)
        return {"ok": False, "err": str(e)[:120], "scores": {}, "weak": []}
    return {"ok": True, "scores": scores,
            "weak": [{"concept": c, "score": s} for c, s in weak]}

def api_theme(name, learning_dir=None):
    """GET /api/theme?name=xx: 返回该主题的覆盖层 CSS(前端原地换肤即时生效)"""
    css = theme.override_css(str(name or ""), target="dashboard")
    normalized = theme.get_theme(name) is not None and \
        str(name or "").strip().lower() in theme.THEMES
    return {"ok": True,
            "name": str(name or "").strip().lower() if normalized else theme.DEFAULT_THEME,
            "css": css}

def api_search(q, learning_dir=None, limit=20):
    """GET /api/search?q=xx: 全文检索(任务/笔记/知识点/标签), 片段已高亮"""
    try:
        hits = search.search(learning_dir or config.BASE, str(q or ""), limit=int(limit))
    except Exception as e:
        logging.error("Boundary error in api_search: %s", e, exc_info=True)
        return {"ok": False, "err": str(e)[:120], "hits": []}
    return {"ok": True, "q": q, "hits": hits}

def api_firstrun(direction, learning_dir=None, today=None):
    """POST /api/firstrun {direction}: 初始化缺失结构 + 生成八周路线图骨架"""
    direction = str(direction or "").strip()
    if not direction:
        return {"ok": False, "err": "缺少 direction(学习方向)"}
    ld = learning_dir or config.BASE
    ws = firstrun.ensure_workspace(ld)
    rp = firstrun.generate_roadmap(direction, ld, today=today)
    return {"ok": True, "created": ws["created"], "existed": ws["existed"],
            "roadmap": rp}

def api_help():
    """GET /api/help: 内置帮助正文(前端 mdmini 渲染, 与周报/报告同管线)"""
    return {"ok": True, "markdown": helpcenter.get_help_markdown()}


__all__ = [
    "api_daily_focus", "_focus_impl",
    "api_get_settings", "api_post_settings", "api_patch_done_at", "api_snooze_all",
    "api_fatigue_state", "api_fatigue_toggle",
    "_load_operations", "log_op", "api_undo",
    "api_analytics", "api_due_reviews", "api_mark_reviewed", "api_retention",
    "api_export", "api_import", "api_backup_now",
    "api_list_reports", "api_read_report",
    "api_mastery", "api_theme", "api_search", "api_firstrun", "api_help",
]
