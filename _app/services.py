# -*- coding: utf-8 -*-
"""services.py —— 业务逻辑层（原 build_dashboard.py K 类, Phase 2.3 迁移）。

依赖: data / utils / config + 外部业务模块(planner/heatmap/duration)。
统一通过模块对象动态访问（data.save_tasks / config.TODAY），便于测试 patch 数据隔离。
"""
import os
import re
import json
import hashlib
import datetime
import logging
import urllib.request

import planner
import heatmap
import duration

from _app import config, data
from _app.utils import next_day


def _expire_fatigue_meta(st=None):
    """v1.7: meta.fatigue_override 次日自动重置(惰性式)。
    为什么放读取侧: 不需要定时器或后台线程——任何一次页面渲染或 POST 都会
    顺带触发检查; date 不是今天就整体清除, 当天内反复读写保持稳定。"""
    st = st if st is not None else data.load_tasks()
    meta = st.get("meta")
    if isinstance(meta, dict):
        fo = meta.get("fatigue_override")
        if isinstance(fo, dict) and fo.get("date") != config.TODAY:
            meta.pop("fatigue_override", None)
            data.save_tasks(st)
    return st


def init_today_from_daily(state, daily_md):
    days = state.setdefault("days", {})
    if days.get(config.TODAY):
        return state, 0
    items = []
    if daily_md:
        for mm in re.finditer(r"^\s*-\s+\[( |x|X)\]\s+(.*)$", daily_md, re.M):
            it = {
                "id": "t-%s-%02d" % (config.TODAY.replace("-", ""), len(items) + 1),
                "text": mm.group(2).strip(),
                "done": mm.group(1).lower() == "x",
                "carried": False,
                "src_date": config.TODAY,
            }
            em = duration.parse_duration(it["text"])   # v1.8 A3: 预估耗时结构化
            if em:
                it["est_minutes"] = em                 # 解析不出就不造字段(诚实)
            items.append(it)
    days[config.TODAY] = items
    state.setdefault("log", []).append({"date": config.TODAY, "event": "init", "count": len(items)})
    data.save_tasks(state)
    return state, len(items)


def rollover(state, from_date, persist=True):
    """明日规划规则:
    1) 部分完成 -> 未勾选进入次日, 带 carried 标记
    2) 0 勾选   -> 整批顺延
    3) 全部完成 -> 无遗留
    """
    days = state.setdefault("days", {})
    bucket = days.get(from_date) or []
    if not bucket:
        return "(%s) 无任务" % from_date
    undone = [t for t in bucket if not t.get("done")]
    moved_n = defer2_n = drop_n = 0
    fatigued = False
    if undone:
        fatigued = planner.is_fatigued(state)
        split = planner.fatigue_split(undone, fatigued)
        move = planner.sort_for_defer(split["move"])
        nd = next_day(from_date)
        ndb = days.setdefault(nd, [])
        for t in move:
            t["carried"] = True
            t["src_date"] = t.get("src_date", from_date)
            if not any(x.get("id") == t["id"] for x in ndb):
                ndb.append(t)
        moved_n = len(move)
        if split["defer2"]:
            d2 = (datetime.date.fromisoformat(from_date) + datetime.timedelta(days=2)).isoformat()
            d2b = days.setdefault(d2, [])
            for t in split["defer2"]:
                t["carried"] = True
                t["defer2"] = True
                t["src_date"] = t.get("src_date", from_date)
                if not any(x.get("id") == t["id"] for x in d2b):
                    d2b.append(t)
            defer2_n = len(split["defer2"])
        if split["drop"]:
            state.setdefault("log", []).append({"date": config.TODAY, "event": "drop_p3",
                                                "ids": [t.get("id") for t in split["drop"]]})
            drop_n = len(split["drop"])
    days[from_date] = [t for t in bucket if t.get("done")]
    extra = ""
    if fatigued:
        extra += " 【疲劳模式】"
    if defer2_n:
        extra += ", 延后2天 %d 条(P2)" % defer2_n
    if drop_n:
        extra += ", 丢弃低优 %d 条(P3)" % drop_n
    if not undone:
        desc = "(%s) 全部完成, 无遗留" % from_date
    elif len(undone) == len(bucket):
        desc = "(%s) 整批顺延 %d 条%s" % (from_date, len(undone), extra)
    else:
        desc = "(%s) 部分顺延 %d/%d 条%s" % (from_date, len(undone), len(bucket), extra)
    state.setdefault("log", []).append({"date": config.TODAY, "event": "rollover", "from": from_date, "to": (next_day(from_date) if undone else None), "moved": len(undone), "desc": desc})
    if persist:
        data.save_tasks(state)
    return desc


def auto_catchup(state, persist=True):
    """日切自动检测: 早于今天的桶里有未完成 -> 逐日滚入(最多链式10跳)"""
    msgs = []
    for _ in range(10):
        expired = [d for d, b in state.get("days", {}).items()
                   if d < config.TODAY and any(not t.get("done") for t in b)]
        if not expired:
            break
        msgs.append(rollover(state, sorted(expired)[0], persist=persist))
    return msgs


def maybe_mark_reviewed(task):
    """Phase C-D: 复习完成反馈 —— 复习任务(done 转换)完成时自动打卡 mark_reviewed。

    幂等由调用方保证(仅在 False->True 转换瞬间调用); 本函数只做 best-effort:
      - review_concept 缺失/为空 -> no-op(返回 False, 零副作用);
      - forgetting.mark_reviewed 异常(IO/未建档) -> 吞掉记日志, 绝不打断/回滚任务完成。
    返回 mark_reviewed 结果; False 不抛错。"""
    concept = str((task or {}).get("review_concept") or "").strip()
    if not concept:
        return False
    try:
        import forgetting
        ok = forgetting.mark_reviewed(config.BASE, concept)
        if not ok:
            logging.warning("maybe_mark_reviewed: 概念未建档, 跳过 %r", concept)
        return ok
    except Exception as e:                              # 完成链路绝不能被复习打卡拖垮
        logging.warning("maybe_mark_reviewed 失败(不影响任务完成): %s", e)
        return False


def persist_compose_diagnostic(state, comp):
    """Phase E-B: 把 compose 诊断(requested_budget/final_count)写入 history 末条,
    让「计划 vs 实际」成为可回测信号(E-A 审计: 原诊断只在响应后即丢弃)。
    无 history / comp 缺字段 -> 静默 no-op; 旧记录无新字段, 消费者兼容。"""
    hist = (state or {}).get("history") or []
    if not hist or not isinstance(comp, dict):
        return False
    last = hist[-1]
    if not isinstance(last, dict):
        return False
    last["budget"] = comp.get("requested_budget")
    last["final"] = comp.get("final_count")
    return True


def toggle(state, tid, done):
    for t in state.get("days", {}).get(config.TODAY, []):
        if t.get("id") == tid:
            was_done = bool(t.get("done"))              # Phase C-D: 转换判定须用旧值
            t["done"] = bool(done)
            if done:
                t["done_at"] = datetime.datetime.now().isoformat(timespec="seconds")   # v1.6: 专注时段数据源
            else:
                t.pop("done_at", None)                                                 # 取消即作废, 重勾重记
            data.save_tasks(state)
            # Phase C-D: 复习反馈 —— 仅 False->True 转换时标记(True->True / True->False 均不触发)
            if done and not was_done:
                maybe_mark_reviewed(t)
            b = state["days"][config.TODAY]
            return True, sum(1 for x in b if x["done"]), len(b)
    return False, 0, 0


# ---------------- v1.3 键盘/拖拽/批量 的后端原语(纯函数, 可单测) ----------------
def reorder_tasks(state, ids, date=None):
    """按 ids 顺序重排指定日期桶(默认今天)。
    ids 未覆盖的任务保持原相对顺序追加在尾部; 未知 id 记入 missing 不致命。"""
    days = state.setdefault("days", {})
    ds = date or config.TODAY
    bucket = days.get(ds)
    if not isinstance(bucket, list):
        return {"ok": False, "err": "该日期无任务桶"}
    want = [str(i) for i in (ids or []) if str(i)]
    if not want:
        return {"ok": False, "err": "ids 为空"}
    by_id, rest = {}, []
    for t in bucket:
        tid = str(t.get("id"))
        if tid in want and tid not in by_id:
            by_id[tid] = t
        else:
            rest.append(t)
    days[ds] = [by_id[i] for i in want if i in by_id] + rest
    state.setdefault("log", []).append({
        "date": config.TODAY, "event": "reorder", "to": ds,
        "count": len(by_id), "missing": [i for i in want if i not in by_id]})
    return {"ok": True, "moved": len(by_id),
            "missing": [i for i in want if i not in by_id]}


def batch_tasks(state, action, ids, value=None, date=None):
    """批量原语: done(勾/取消) | delete(整行删除) | priority(1~3 钳制)。
    空 ids / 未知动作一律拒收且零改动; 动作成功写 log 留账。"""
    days = state.setdefault("days", {})
    ds = date or config.TODAY
    bucket = days.get(ds)
    if not isinstance(bucket, list):
        return {"ok": False, "err": "该日期无任务桶"}
    want = {str(i) for i in (ids or []) if str(i)}
    if not want:
        return {"ok": False, "err": "ids 为空"}
    if action == "snooze":                       # v1.9 C4: 整批顺延到明天(仅未完成项)
        import datetime as _dt
        nxt = (_dt.datetime.strptime(ds, "%Y-%m-%d") + _dt.timedelta(days=int(value or 1))).strftime("%Y-%m-%d")
        moved, keep = [], []
        for t in bucket:
            if str(t.get("id")) in want and not t.get("done"):
                t["carried"] = True
                days.setdefault(nxt, []).append(t)
                moved.append(str(t.get("id")))
            else:
                keep.append(t)
        days[ds] = keep
        state.setdefault("log", []).append({"date": config.TODAY, "event": "batch_snooze", "count": len(moved)})
        return {"ok": True, "affected": len(moved), "moved_ids": moved,
                "to_date": nxt, "undo": {"ids": moved, "to_date": nxt}}
    if action == "done":
        val = bool(value) if value is not None else True
        n = 0
        for t in bucket:
            if str(t.get("id")) in want:
                t["done"] = val
                if val:
                    t["done_at"] = datetime.datetime.now().isoformat(timespec="seconds")   # 与单条勾选同口径
                else:
                    t.pop("done_at", None)
                n += 1
        state.setdefault("log", []).append(
            {"date": config.TODAY, "event": "batch_done", "count": n, "value": val})
        return {"ok": True, "affected": n}
    if action == "delete":
        keep = [t for t in bucket if str(t.get("id")) not in want]
        removed = len(bucket) - len(keep)
        days[ds] = keep
        state.setdefault("log", []).append(
            {"date": config.TODAY, "event": "batch_delete", "count": removed})
        return {"ok": True, "affected": removed}
    if action == "priority":
        try:
            pri = max(1, min(3, int(value if value is not None else 2)))
        except (TypeError, ValueError):
            pri = 2
        n = 0
        for t in bucket:
            if str(t.get("id")) in want:
                t["priority"] = pri
                n += 1
        state.setdefault("log", []).append(
            {"date": config.TODAY, "event": "batch_priority", "count": n, "value": pri})
        return {"ok": True, "affected": n}
    return {"ok": False, "err": "未知动作: %s" % action}


# ---------------- Phase B: 明日预算闭环 compose_tomorrow ----------------
_COMPOSE_ID_PREFIX = "c-"


def _compose_task_id(line_id, text, phase, milestone):
    """确定性任务 id(仿 weakspot.task_id): 同内容跨日跨周稳定, 是全库去重的基石。
    刻意不含 target_date: 同一池条目无论为哪一天生成, 身份唯一 -> 永不重复生成。"""
    raw = "|".join([str(line_id), str(text), str(phase or ""), str(milestone or "")])
    return _COMPOSE_ID_PREFIX + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def _active_window_lines(plan_data, on_date):
    """返回 on_date 落在 priority_windows 内的线 id 集合。
    最小内部 helper(Phase A §10 允许): 与渲染层 plan 面板同口径, 不重复维护。"""
    active = set()
    for w in (plan_data or {}).get("priority_windows", []) or []:
        try:
            wf = datetime.date.fromisoformat(w.get("from", ""))
            wt = datetime.date.fromisoformat(w.get("to", ""))
        except (TypeError, ValueError):
            continue
        if wf <= on_date <= wt:
            active.add(str(w.get("line", "")))
    return active


def _collect_pool_candidates(plan_data, on_date):
    """把 plan.json 各线 task_pool 展开为候选 [(sort_key, line_id, text, pri, phase, milestone)]。
    坏条目/无池/坏池一律静默跳过(不报错、不发明任务文本); 排序全确定性:
    优先级降序 -> 活动优先窗口的线在前 -> 线序 -> 条目序。"""
    if not isinstance(plan_data, dict):
        return []
    active = _active_window_lines(plan_data, on_date)
    out = []
    for li, ln in enumerate(plan_data.get("lines", []) or []):
        if not isinstance(ln, dict):
            continue
        pool = ln.get("task_pool")
        if not isinstance(pool, list):
            continue                       # 无 task_pool / 非列表 -> 跳过该线
        lid = str(ln.get("id", ""))
        for ii, e in enumerate(pool):
            if not isinstance(e, dict):
                continue
            text = str(e.get("text", "") or "").strip()
            if not text:
                continue
            try:
                pri = max(1, min(3, int(e.get("priority", 2))))
            except (TypeError, ValueError):
                pri = 2
            key = (pri, 0 if lid in active else 1, li, ii)
            out.append((key, lid, text, pri, e.get("phase"), e.get("milestone")))
    return out


# ---------------- Phase C-B: 复习源(到期知识点 -> 明日任务) ----------------
_REVIEW_ID_PREFIX = "c-rev-"
_REVIEW_NOISE_SET = {
    "##", "#", "md", "py", "txt", "json", "csv", "html", "css", "js",
    "交付", "冒烟", "todo", "done", "check", "wip", "tbd", "fixme",
}
_REVIEW_WEEKDAYS = {
    "周一", "周二", "周三", "周四", "周五", "周六", "周日",
    "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
}
_REVIEW_NOISE_RE_FILE = re.compile(r"[\w.-]+\.(?:md|py|txt|json|csv|html|css|js)$", re.I)
_REVIEW_NOISE_RE_SYMBOL = re.compile(r"^[^\w\u4e00-\u9fff]+$")   # 纯符号(## *** --- 等)


def _is_review_noise(concept):
    """Phase C-B: 拒绝噪音概念 —— 单字符/纯数字/纯符号/文件与路径/
    仓库既有噪音词(交付冒烟等)/星期词。返回 True = 该概念不可作为复习任务。"""
    s = str(concept or "").strip()
    if not s or len(s) < 2:
        return True
    if s.isdigit():
        return True
    if s in _REVIEW_NOISE_SET or s in _REVIEW_WEEKDAYS:
        return True
    if re.search(r"[./\\]", s):                       # 文件/扩展/路径
        return True
    if _REVIEW_NOISE_RE_SYMBOL.match(s):              # 纯符号
        return True
    if _REVIEW_NOISE_RE_FILE.match(s):
        return True
    return False


def _norm_review_text(text):
    """归一化任务文本用于「等价去重」: 去「复习:」前缀、去空白、小写。
    使「复习: Python 切片」与手工任务「Python 切片」视为等价。"""
    return re.sub(r"复习[:：]\s*", "", str(text or "")).replace(" ", "").lower()


def _resolve_review_topic(analysis, concept, source_date):
    """Phase C-B + D-B: 解析人类可读复习标签, 回退顺序:
      归一化 label > 显式 tag > existing topic > concept。
    归一化(normalize.normalize_concepts)失败/未启用 -> 安全回退旧逻辑, 不破坏 Phase C。"""
    try:
        notes = (analysis or {}).get("notes", {}) or {}
        rec = notes.get(str(source_date)) or {}
        # D-B: 归一化 label 优先(高质量可读名)。仅当 label 与 concept 不同
        # (即词汇表/规范名命中, 真·更可读)时才采用; 否则继续回退 tag/topic,
        # 避免归一化回退出的 concept 原文短路掉更有信息量的 topic。
        try:
            import normalize
            norms = normalize.normalize_concepts(rec)
            for n in norms:
                if _stable_key(n.get("concept")) == _stable_key(concept):
                    lbl = str(n.get("label") or "").strip()
                    # 原始字符串不同(含大小写规范如 mcp->MCP)即视为「更可读」采用;
                    # 完全一致(归一化回退出 concept 原文)才跳过, 避免短路 topic 回退
                    if lbl and lbl != str(concept):
                        return lbl
        except Exception:
            pass
        # 回退: 显式 tag(首个非噪声)
        for t in rec.get("tags") or []:
            t = str(t).strip()
            if t and not _is_review_noise(t):
                return t
        # 回退: 既有 topic
        topic = str(rec.get("topic") or "").strip()
        if topic:
            return topic
    except Exception:
        pass
    return str(concept or "")


def _stable_key(text):
    """与 normalize._stable_key 同口径的稳定键(避免跨模块 import 耦合)。"""
    import re as _re
    return _re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _collect_review_candidates(learning_dir, today):
    """Phase C-B: 到期复习候选。forgetting.due_cards(最弱在前) -> 噪音过滤 ->
    按 source_date 单笔记封顶。analysis/knowledge 缺失或异常 -> 空列表(安全降级, 不报错)。"""
    if not learning_dir:
        return []
    try:
        import forgetting
        cards = forgetting.due_cards(learning_dir, today=today)
    except Exception as e:
        logging.warning("review candidates skipped: %s", e)
        return []
    try:
        import analyzer
        analysis = analyzer.load_analysis(learning_dir)
    except Exception:
        analysis = None
    seen_dates, out = set(), []
    for c in cards:                                  # 已按 (retention, -count, concept) 最弱在前
        concept = str(c.get("concept") or "").strip()
        if not concept or _is_review_noise(concept):
            continue
        sd = str(c.get("source_date") or "")
        if not sd or sd in seen_dates:
            continue                                 # 同一 source_date 的笔记最多生成一条
        seen_dates.add(sd)
        topic = _resolve_review_topic(analysis, concept, sd)
        if not topic:
            continue
        out.append({"concept": concept, "source_date": sd,
                    "topic": topic, "retention": c.get("retention", 100)})
    return out


def compose_tomorrow(state, target_date, budget, cfg=None):
    """Phase B+C: 明日预算闭环 —— 到期复习(Phase C-B)优先 + 四线任务池补足明日桶。

    语义(Phase B 规格 + C-B 复习源):
      - budget = 明日期望总任务数; 桶内既有任务(rollover 顺延等)先计入预算;
      - remaining = max(0, budget - 既有数), 只补缺口, 绝不删改既有任务;
      - 复习源(Phase C-B): cfg["learning_dir"] 存在时, 取 forgetting.due_cards 到期概念,
        噪音过滤 -> source_date 解析 analysis 标题 -> 生成「复习:<标题>」任务;
        单 source_date 笔记最多一条; 复习任务 priority=1 且先于 task_pool 占预算;
        确定性 id(c-rev-+md5(concept)) + 全库去重 + 等价文本去重(即使 id 不同);
        携带 review_concept/review_source_date 元数据, 供日后 mark_reviewed 打卡复用;
      - task_pool 候选确定性 id(c-+md5) + 全库去重(仿 weakspot);
      - 纯内存变更不落盘(持久化归调用方), 幂等可重复调用;
      - 无 AI/LLM 生成、不随机采样; budget<=0/非法 -> 零生成;
      - plan.json 缺失/无池/池全在库 -> 优雅降级为少生成或零生成。
    cfg: 测试注入 {"plan": {...}} 可绕过磁盘读取; {"learning_dir":..., "today":...} 启用复习源。
    返回诊断: {requested_budget, existing_count, remaining_slots,
              generated_count, review_generated, generated, final_count, note}
    """
    days = state.setdefault("days", {})
    bucket = days.setdefault(target_date, [])
    existing = len(bucket)
    out = {"target_date": target_date, "requested_budget": budget,
           "existing_count": existing, "remaining_slots": 0,
           "generated_count": 0, "review_generated": 0,
           "generated": [], "final_count": existing, "note": ""}
    try:
        b = int(budget)
    except (TypeError, ValueError):
        out["note"] = "budget 非法, 零生成"
        return out
    if b <= 0:
        out["note"] = "budget<=0, 零生成"
        return out
    remaining = max(0, b - existing)
    out["remaining_slots"] = remaining
    if remaining == 0:
        out["note"] = "既有任务已达预算, 零生成"
        return out
    plan_data = (cfg or {}).get("plan", "__MISSING__")
    if plan_data == "__MISSING__":     # cfg 未提供 plan 键才读磁盘; 显式 None = 无池(测试注入)
        plan_data = data.load_plan()
    # 全库 id 集合(跨所有桶) —— 去重不只看目标桶
    have = set()
    for bk in days.values():
        for t in bk:
            if isinstance(t, dict) and t.get("id"):
                have.add(str(t["id"]))
    try:
        on_date = datetime.date.fromisoformat(target_date)
    except (TypeError, ValueError):
        on_date = None
    cands = _collect_pool_candidates(plan_data, on_date) if on_date else []
    generated = []
    # ---- Phase C-B: 复习源优先(预算内先于 task_pool) ----
    ldir = (cfg or {}).get("learning_dir")
    rtoday = (cfg or {}).get("today") or target_date
    if isinstance(rtoday, str):
        try:
            rtoday = datetime.date.fromisoformat(str(rtoday)[:10])
        except (TypeError, ValueError):
            rtoday = None
    existing_norms = {_norm_review_text(t.get("text")) for t in bucket
                      if isinstance(t, dict)}
    review_generated = 0
    if ldir and rtoday is not None and remaining > 0:
        for rv in _collect_review_candidates(ldir, rtoday):
            if len(generated) >= remaining:
                break
            tid = _REVIEW_ID_PREFIX + \
                hashlib.md5(rv["concept"].encode("utf-8")).hexdigest()[:8]
            if tid in have:
                continue                              # 全库 id 去重
            if _norm_review_text("复习：" + rv["topic"]) in existing_norms:
                continue                              # 等价文本去重(即使 id 不同)
            task = {"id": tid, "text": "复习：" + rv["topic"], "done": False,
                    "carried": False, "src_date": target_date, "priority": 1,
                    "track": "review",
                    "review_concept": rv["concept"],
                    "review_source_date": rv["source_date"]}
            bucket.append(task)
            have.add(tid)
            existing_norms.add(_norm_review_text(task["text"]))
            generated.append(task)
            review_generated += 1
    for _key, lid, text, pri, phase, milestone in sorted(cands, key=lambda c: c[0]):
        if len(generated) >= remaining:
            break
        tid = _compose_task_id(lid, text, phase, milestone)
        if tid in have:
            continue                       # 全库去重: 已存在(任何桶)即跳过, 槽位留给后续候选
        task = {"id": tid, "text": text, "done": False, "carried": False,
                "src_date": target_date, "priority": pri, "track": lid}
        bucket.append(task)
        have.add(tid)
        generated.append(task)
    out["generated"] = [{"id": t["id"], "text": t["text"], "line": t["track"],
                         **({"review_concept": t["review_concept"]} if t.get("review_concept") else {})}
                        for t in generated]
    out["generated_count"] = len(generated)
    out["review_generated"] = review_generated
    out["final_count"] = len(bucket)
    if generated == [] and cands:
        out["note"] = "候选均已在库(去重), 零生成"
    elif generated == [] and review_generated == 0 and ldir:
        out["note"] = "无到期复习概念或候选均在库, 零生成"
    elif not cands and review_generated == 0:
        out["note"] = "无可用任务池(plan.json 未配置或各线无 task_pool)"
    return out


# ---------------- v0.6 AI 周报 ----------------
def extract_keywords(texts, topn=8):
    """朴素中文关键词: 2~4字片段词频 TopN(含少量停用字过滤), 无第三方库"""
    stop = set("的了和是有在就不人都一个上也为这那你说它们我们你们自己什么没有还是但与及或之其此些很更最还再又才只等被把让向往从到于对会能可以要想着看听读写做用去来过吧吗呢啊呀哦嗯如果因为所以然后觉得开始完成学习今天明天内容问题进行使用实现".split())
    cnt = {}
    for t in texts:
        for w in re.findall(r"[一-鿿]{2,4}", t):
            if w in stop:
                continue
            cnt[w] = cnt.get(w, 0) + 1
    return [w for w, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:topn]]


def weekly_report(state, learning_dir):
    """聚合真实数据生成周报; 有 DEEPSEEK_API_KEY 时走 DeepSeek 增强, 失败一次即降级本地模板(熔断)"""
    stats = planner.get_stats(state)
    hist7 = state.get("history", [])[-7:]
    fat = planner.detect_fatigue(state)
    tm = planner.predict_tomorrow(state)
    notes = heatmap.scan_daily(learning_dir, with_text=True)
    today = datetime.date.today()
    week_dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    week_notes = [notes[d] for d in week_dates if d in notes]
    titles = [n["title"] for n in week_notes]
    kws = extract_keywords([n.get("_text", "") for n in week_notes])
    detail = " | ".join("%s %d/%d%s" % (h["date"][5:], h["done"], h["total"],
                         "✅" if h.get("rate", 0) >= 0.8 else "") for h in hist7) or "近7天无收尾记录"
    trend = "上升" if tm["slope"] > 0.02 else ("下降" if tm["slope"] < -0.02 else "平稳")
    md = ("# 学习周报 · %s ~ %s\n\n" % (week_dates[0], week_dates[-1])
          + "## 一、完成度总结\n"
          + "- 近7天有记录 **%d** 天，平均完成率 **%d%%**（30日 %d%%）\n" % (len(hist7), round(stats["avg7"] * 100), round(stats["avg30"] * 100))
          + "- 每日明细：%s\n" % detail
          + "- 最长连续达标：**%d** 天\n" % stats["max_streak"]
          + "- 本周笔记：**%d** 篇，共 %d 字\n\n" % (len(week_notes), sum(n.get("chars", 0) for n in week_notes))
          + "## 二、笔记精华\n"
          + "- 高频关键词：%s\n" % ("、".join(kws) if kws else "（本周暂无笔记内容）")
          + "- 篇目：%s\n\n" % ("；".join(titles) if titles else "（无）")
          + "## 三、下周建议\n"
          + ("- 疲劳状态：🔥 疲劳中（%s）→ 任务上限受 cap 约束，只保 P1，先恢复节奏\n" % fat.get("reason", "") if fat.get("active") else "- 疲劳状态：✅ 正常\n")
          + "- 完成率趋势：%s（斜率 %+.3f）→ 建议%s任务量\n" % (trend, tm["slope"], "适度增加" if tm["slope"] > 0.02 else ("酌情减负" if tm["slope"] < -0.02 else "维持当前"))
          + "- 引擎预测明日建议量：**%d 条**\n" % tm["predicted"])
    # ---- Phase B1 素材: 概念摘要聚合 + 本周复习/掌握趋势(失败静默降级为空, 不影响主流程) ----
    concept_summaries, review_trend = [], []
    try:
        import forgetting as _fg
        kdata = _fg.load_knowledge(learning_dir)
        kn = kdata.get("knowledge") or {}
        for c, rec in sorted(kn.items()):
            if not c or not isinstance(rec, dict):
                continue
            row = {"concept": str(c)[:40],
                   "review_count": int(rec.get("review_count", 0) or 0),
                   "stability": rec.get("stability"),
                   "difficulty": rec.get("difficulty")}
            # analyzer 的 summary(笔记提炼的一句话摘要)并入
            try:
                import analyzer as _az
                an = _az.load_analysis(learning_dir)
                for ds in sorted((an.get("notes") or {}).keys()):
                    nrec = an["notes"][ds]
                    if c in (nrec.get("concepts") or []):
                        s = str(nrec.get("summary") or "").strip()
                        if s:
                            row["summary"] = s[:80]
                            break
            except Exception:
                pass
            concept_summaries.append(row)
        # 本周复习趋势: 由 review_log 近 7 天事件统计
        recent = 0
        for e in (kdata.get("review_log") or []):
            if isinstance(e, dict) and e.get("ts"):
                try:
                    ts_day = datetime.datetime.fromisoformat(str(e["ts"])[:19]).date()
                    if (today - ts_day).days <= 7:
                        recent += 1
                except Exception:
                    pass
        review_trend = {"last7_reviews": recent,
                        "mastery_low_count": sum(
                            1 for r in kn.values() if isinstance(r, dict)
                            and (r.get("mastery_score") is not None)
                            and r.get("mastery_score", 0) < 40)}
    except Exception:
        concept_summaries, review_trend = [], []
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {"ok": True, "source": "template", "markdown": md}
    # ---- Phase B1(2026-09-03): 复用 analyzer 的 _call_deepseek + _LLM_DISABLED 熔断基建,
    # 不再自建 urllib 调用(原自建分支为重复建设, 已收敛到 analyzer 单一出口) ----
    try:
        import analyzer
        payload = {"stats": stats, "hist7": hist7, "fatigue": fat, "predict": tm,
                   "note_titles": titles, "keywords": kws,
                   "concept_summaries": concept_summaries, "review_trend": review_trend}
        insight = analyzer.llm_weekly_insight(payload, key)
        if insight:
            md = md + "\n\n## 四、本周洞察（AI）\n\n- " + insight + "\n"
            return {"ok": True, "source": "deepseek", "markdown": md}
        return {"ok": True, "source": "template", "markdown": md}   # 无 Key / 熔断 / 失败: 完整回退
    except Exception as e:
        logging.error("Boundary error in weekly_report: %s", e, exc_info=True)
        return {"ok": True, "source": "template",
                "markdown": md + "\n\n> （DeepSeek 调用未成功，已降级本地模板：%s）" % str(e)[:80]}


__all__ = [
    "_expire_fatigue_meta", "init_today_from_daily", "rollover", "auto_catchup",
    "toggle", "reorder_tasks", "batch_tasks", "extract_keywords", "weekly_report",
]
