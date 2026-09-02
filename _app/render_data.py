# -*- coding: utf-8 -*-
"""render_data.py —— Dashboard 数据准备层 (D-5c)

职责: 输入 BASE/TODAY -> 业务数据 + ViewModel(HTML 片段) -> dict。
  - 无模板 / 无资源注入(css/js/theme 由 renderer 层读取)
  - 写盘副作用(update_analysis/sync_from_analysis/weak_concepts)显式保留
    (渲染即同步语义, 与 D-5b 前一致)
依赖方向: renderer.py -> render_data.py (单向, 无循环 import)
"""
import os
import urllib
import datetime

import planner
import adaptive
import forgetting
import analyzer
import theme
import settings
import heatmap
import recommender
import mastery
import reportio
import duration

from _app import config, data, services, utils


# 概念展示层归一化: knowledge.json 的概念由 analyzer 提取, 部分含原始解析 token
# (##/api/md/py/selftest/trending 等)。这些 ID 是权威数据, 不在源端修改,
# 仅在渲染层映射为人类可读标签, 避免界面暴露机器 token。
_CONCEPT_LABELS = {
    "##": "Markdown 标题",
    "api": "API 接口",
    "md": "Markdown",
    "py": "Python",
    "selftest": "自测用例",
    "trending": "热点趋势",
}


def _clabel(concept):
    """概念展示归一化: 已知机器 token -> 可读标签; 其余(含中文/正常词)原样返回。"""
    if not concept:
        return concept
    return _CONCEPT_LABELS.get(concept.strip(), concept.strip())


def build_context(base, today, interactive=True):
    """数据准备 + ViewModel 构建(纯数据层, 无模板)。返回 dict。"""
    # 依赖绑定(便于测试 patch 数据隔离)
    read_file = data.read_file
    load_status = data.load_status
    load_tasks = data.load_tasks
    load_plan = data.load_plan
    esc_inline = utils.esc_inline
    esc_attr = utils.esc_attr
    md_to_html = utils.md_to_html
    empty_block = utils.empty_block
    section = utils.section
    bar = utils.bar
    plan_hint = utils.plan_hint
    safe_task = utils.safe_task
    _ret_color = utils._ret_color
    init_today_from_daily = services.init_today_from_daily
    auto_catchup = services.auto_catchup

    BASE = base
    TODAY = today
    INTERACTIVE = interactive

    # P0-1: STATUS.json 经 data.load_status() 读取(utf-8-sig 兼容记事本 BOM)。
    # 旧路径 read_file(utf-8) 遇 BOM 抛 JSONDecodeError -> status={} -> pct="?" 占位符。
    status = load_status()
    roadmap = read_file("ROADMAP.md") or "(未找到 ROADMAP.md)"
    profile = read_file("PROFILE.md") or "(未找到 PROFILE.md)"
    daily = read_file(os.path.join("daily", TODAY + ".md"))

    st = load_tasks()
    _, n_init = init_today_from_daily(st, daily)
    catchups = auto_catchup(st)
    bucket = st.get("days", {}).get(TODAY, [])
    dn = sum(1 for t in bucket if t.get("done"))
    tn = len(bucket)
    tp = int(round(dn * 100 / tn)) if tn else 0

    task_html = ""
    planner.normalize_priorities(st)
    for t in bucket:
        t = safe_task(t)
        tag = ' <span class="tag">顺延</span>' if t["carried"] else ""
        if t["defer2"]:
            tag += ' <span class="tag">延后2天</span>'
        pri = t["priority"]
        est_tag = (' <span class="tag">' + esc_attr(duration.format_badge(t["est_minutes"])) +
                   "</span>") if t["est_minutes"] else ""
        # P2 不显示标签(默认值); P1/P3 显示; class pptag 供右键菜单就地更新
        ptag = (' <span class="tag pptag"%s>P%d</span>' % ("" if pri != 2 else ' style="display:none"', pri))
        done_cls = "task ck completed" if t["done"] else "task ck"
        src_d = esc_attr(t["src_date"])
        editor_url = esc_attr("/editor?date=" + urllib.parse.quote(src_d, safe=""))
        done_at_html = ""
        if t["done_at"]:
            done_at_text = esc_attr(str(t["done_at"])[:16].replace("T", " "))
            done_at_html = ' · 🕐 完成于 ' + done_at_text
        tid = esc_attr(t["id"])
        checked = "checked" if t["done"] else ""
        task_html += (
            f'<label class="{esc_attr(done_cls)}" data-id="{tid}" '
            f'data-pri="{pri}" tabindex="0" draggable="true" '
            f'oncontextmenu="ctxmenu(event,this.dataset.id,this.dataset.pri)" '
            f'ondragstart="dragStart(event,this)" '
            f'ondragover="dragOver(event,this)" '
            f'ondrop="dropTask(event,this)" ondragend="clearDrag()">'
            f'<input type="checkbox" data-id="{tid}" {checked} '
            f'onchange="tg(this.dataset.id,this)">'
            f'<span class="hact"><button data-a="done" title="完成">✓</button>'
            f'<button data-a="snooze" title="顺延">⏭</button>'
            f'<button data-a="edit" title="展开详情">✏️</button></span>'
            f'<span class="txt">{esc_attr(t["text"])}{tag}{ptag}{est_tag}</span>'
            f'<span class="tdetail">P{pri} · 来源 {src_d} · '
            f'<a href="{editor_url}">相关笔记</a>{done_at_html}</span>'
            f'</label>')
    if not task_html:
        task_html = empty_block("notebook", "今天还没有任务——在 daily 笔记里写一条 checkbox，或点「📝 写笔记」开始")
    if not INTERACTIVE:
        task_html = ('<div class="notice">静态快照(只读)：双击「打开学习仪表盘.bat」进入交互模式才能勾选</div>' + task_html)

    pct = status.get("total_percent", "?")
    subj_html = ""
    for s in status.get("subjects", []):
        icon = {"ok": "✅", "warn": "⚠️", "pending": "⏸"}.get(s.get("state", ""), "")
        pc = s.get("percent", 0)
        cls = "fill done" if pc >= 90 else ("fill prog" if pc > 0 else "fill zero")
        subj_html += ('<div class="subj"><span class="sname">%s %s</span><span class="spct">%s%%</span>%s</div>'
                      ) % (s.get("name", ""), icon, pc, bar(pc, cls))

    # ---- 四线并行计划(plan.json) · UI 冻结后新增内容型面板 ----
    # 数据源: plan.json(utf-8-sig, 与 STATUS.json 同规范); 低频手工维护。
    # 一致性铁律: A 线总进度不从 plan.json 读, 而派生自 STATUS.json total_percent
    # (单一事实源), 保证新旧面板(总览环 / pnl-progress 科目条 / 本面板)永远一致。
    plan_data = load_plan()
    plan_html = ""
    plan_lines = plan_data.get("lines", [])
    if plan_lines:
        today_d = datetime.date.fromisoformat(TODAY)
        wins = []
        for w in plan_data.get("priority_windows", []):
            try:
                wf = datetime.date.fromisoformat(w.get("from", ""))
                wt = datetime.date.fromisoformat(w.get("to", ""))
            except (TypeError, ValueError):
                continue
            wins.append((w, wf, wt))
        win_now = next(((w, wf, wt) for w, wf, wt in wins if wf <= today_d <= wt), None)
        win_next = None
        if win_now is None:
            fut = [(w, wf) for w, wf, wt in wins if wf > today_d]
            if fut:
                win_next = min(fut, key=lambda x: x[1])
        lname_of = lambda lid: next((l.get("name", "") for l in plan_lines if l.get("id") == lid), "")
        banner = ""
        if win_now:
            w = win_now[0]
            banner = ('<div class="sub" style="margin:4px 0 8px"><span class="good">⏳ 当前绝对优先</span>：'
                      '<b>%s · %s</b>（至 %s）</div>'
                      % (esc_inline(str(w.get("line", ""))), esc_inline(lname_of(w.get("line"))),
                         esc_attr(w.get("to", ""))))
        elif win_next:
            w = win_next[0]
            banner = ('<div class="sub" style="margin:4px 0 8px">下一个优先窗口：<b>%s · %s</b>（%s ~ %s）</div>'
                      % (esc_inline(str(w.get("line", ""))), esc_inline(lname_of(w.get("line"))),
                         esc_attr(w.get("from", "")), esc_attr(w.get("to", ""))))
        rows = ""
        for ln in plan_lines:
            lid = esc_inline(str(ln.get("id", "")))
            lname = esc_inline(str(ln.get("name", "")))
            goal = esc_inline(str(ln.get("goal", "")))
            phase = esc_inline(str(ln.get("current_phase", "")))
            nm = esc_inline(str(ln.get("next_milestone", "")))
            md = ln.get("milestone_date") or ""
            cnt = ""
            if md:
                try:
                    dleft = (datetime.date.fromisoformat(md) - today_d).days
                except (TypeError, ValueError):
                    dleft = None
                if dleft is not None:
                    cnt = ("还有 %d 天" % dleft) if dleft > 0 else ("今天" if dleft == 0 else "已过 %d 天" % (-dleft))
            if ln.get("id") == "A":
                pc = int(pct) if isinstance(pct, int) else 0   # 单一事实源: STATUS.json
            else:
                try:
                    pc = int(ln.get("total_progress") or 0)
                except (TypeError, ValueError):
                    pc = 0
            cls = "fill done" if pc >= 90 else ("fill prog" if pc > 0 else "fill zero")
            dh = ln.get("daily_hours")
            dht = ("%s h/天" % dh) if dh is not None else ""
            waiting = " ｜ 状态：准备中" if ln.get("status") == "waiting" else ""
            rows += ('<div class="subj"><span class="sname"><span class="tag">%s</span> %s '
                     '<span class="tag">%s</span></span><span class="spct">%d%%</span>%s</div>'
                     '<div class="dim" style="margin:-4px 0 10px 2px">目标：%s%s%s%s</div>'
                     ) % (lid, lname, phase, pc, bar(pc, cls), goal,
                          (" ｜ 下一里程碑：%s（%s）" % (nm, cnt)) if nm and cnt else ((" ｜ 下一里程碑：%s" % nm) if nm else ""),
                          (" ｜ 建议 %s" % dht) if dht else "", waiting)
        plan_html = banner + rows

    milestone_html = md_to_html(section(roadmap, "阶段总览")) or "<p class='dim'>未找到「阶段总览」表</p>"
    review_html = md_to_html(section(roadmap, "当前复习队列"))
    # 知识库: 扫 daily 笔记, 标签聚合 + 最近列表(点击进编辑器)
    notes_all = heatmap.scan_daily(BASE)
    tag_map = {}
    for dstr2 in sorted(notes_all.keys(), reverse=True):
        for tg2 in notes_all[dstr2].get("tags", []):
            tag_map.setdefault(tg2, []).append(dstr2)
    if not notes_all:
        kb = "<p class='dim'>还没有笔记——点顶部「📝 写笔记」开始积累知识资产</p>"
    else:
        kb = ""
        if tag_map:
            kb += "<div style='margin-bottom:8px'>" + "".join(
                "<span class='tag' style='margin:2px 4px 2px 0'>#%s ×%d</span>" % (t2, len(v2))
                for t2, v2 in sorted(tag_map.items(), key=lambda kv: -len(kv[1]))) + "</div>"
        kb += "<table><tbody><tr><th>日期</th><th>标题</th><th>标签</th><th>字数</th></tr>"
        for dstr2 in sorted(notes_all.keys(), reverse=True)[:10]:
            info2 = notes_all[dstr2]
            kb += ("<tr><td>%s</td><td><a href='/editor?date=%s'>%s</a></td><td>%s</td><td>%d</td></tr>"
                   % (dstr2, dstr2, esc_inline(info2["title"]),
                      esc_inline(", ".join(info2.get("tags", []))) or "-", info2["chars"]))
        kb += "</tbody></table>"
    hint = plan_hint(dn, tn)
    fat = planner.detect_fatigue(st)
    tm = planner.predict_tomorrow(st)
    # 概览卡底部状态行: 疲劳红色高亮 / 良好绿色
    if fat.get("active"):
        planline = ('<span class="bad">🔥 疲劳模式（%s）</span> · 明日建议 <b>%d</b> 条'
                    % (esc_inline(fat.get("reason", "")), tm["predicted"]))
    else:
        planline = ('<span class="good">✅ 状态良好</span> · 明日建议 <b>%d</b> 条（7日均 %.1f 条）'
                    % (tm["predicted"], tm["avg7_done"]))
    # 近7天柱状图(CSS flex): 取 history 最近7条的 done 数
    hist7 = st.get("history", [])[-7:]
    if hist7:
        mx = max([h.get("done", 0) for h in hist7] + [1])
        bars = ""
        for h in hist7:
            dnv = h.get("done", 0)
            hgt = max(8, int(dnv * 100 / mx))
            bars += ('<div class="bcol"><div class="bbar" style="height:%d%%" title="%s 完成 %d/%d"></div>'
                     '<div class="blab">%s</div></div>') % (hgt, h.get("date", ""), dnv, h.get("total", 0), (h.get("date", "") or "?")[8:])
    else:
        bars = '<div class="dim" style="align-self:center">暂无 history 数据（点「立即收尾」后自动生成）</div>'
    # SVG 环形进度: 周长 C=2πr, dashoffset=C*(1-完成率)
    CIRC = 2 * 3.141592653589793 * 52
    ratio = (dn / tn) if tn else 0
    ring = ('<svg class="ring" viewBox="0 0 120 120">'
            '<defs><linearGradient id="ringGrad" x1="0%%" y1="0%%" x2="100%%" y2="100%%">'
            '<stop offset="0%%" stop-color="var(--color-accent)"/>'
            '<stop offset="100%%" stop-color="var(--color-accent-hover)"/>'
            '</linearGradient></defs>'
            '<circle cx="60" cy="60" r="52" fill="none" stroke="var(--color-border-subtle)" stroke-width="8"/>'
            '<circle id="ringfg" class="ringfg" cx="60" cy="60" r="52" fill="none" stroke="url(#ringGrad)" stroke-width="8" '
            'stroke-linecap="round" stroke-dasharray="%.1f" stroke-dashoffset="%.1f" transform="rotate(-90 60 60)"/></svg>'
            % (CIRC, CIRC * (1 - ratio)))
    # v0.7 复习卡片: 惰性补齐分析(只分析缺失日期) + 状态筛选
    analyzer.update_analysis(BASE)
    rcards = analyzer.get_review_cards(BASE)
    need = [c for c in rcards if c["status"] == "需复习"]
    n_new = sum(1 for c in rcards if c["status"] == "新学")
    n_mid = sum(1 for c in rcards if c["status"] == "巩固中")
    n_done = sum(1 for c in rcards if c["status"] == "已巩固")
    if need:
        items_html = "".join(
            "<a class='tag rvtag' href='/editor?date=%s' title='打开 %s'>📌 %s · %s</a>"
            % (c["source_date"], c["source_date"], esc_inline(_clabel(c["concept"])), c["source_date"][5:])
            for c in need[:12])
        review = ("<div style='display:flex;flex-wrap:wrap;gap:6px'>" + items_html + "</div>"
                  + "<p class='dim' style='margin-top:8px'>知识点总账：需复习 <b>%d</b> ｜ 新学 %d ｜ 巩固中 %d ｜ 已巩固 %d</p>"
                  % (len(need), n_new, n_mid, n_done))
    else:
        review = "<p class='dim'>✨ 暂无待复习知识点（保存笔记后自动生成）</p>"
    # v0.9 推荐引擎: 每次加载实时计算(不缓存)
    rec_data = recommender.get_recommendations(BASE)
    rec_items = rec_data.get("items", [])
    ricons = {"review": "🔁", "explore": "🔍", "rest": "😴"}
    if rec_data.get("state") == "accumulating":
        rec_html = empty_block("compass", "数据积累中——写笔记、做收尾，推荐引擎会自动开工")
    elif not rec_items:
        rec_html = "<p class='dim'>✅ 当前学习节奏良好，继续保持</p>"
    else:
        rows = ""
        for r0 in rec_items:
            link_html = (" <a href='" + r0["link"] + "'>去处理 →</a>") if r0.get("link") else ""
            rows += ("<div class='rec'><span class='ricon'>" + ricons.get(r0["type"], "•") + "</span>"
                     + "<b class='rcon'>" + esc_inline(_clabel(r0["concept"])) + "</b>"
                     + "<span class='rrsn'>" + esc_inline(r0["reason"]) + link_html + "</span></div>")
        rec_html = rows

    # v1.1 数据闭环: 今日待复习 / 记忆衰减 / 报告清单(全部实时计算, 容错降级)
    # P0-3: due_cards 已按 (retention, -review_count, concept) 确定性排序(最弱优先);
    #       此处直接消费其顺序, 不再二次排序, 并显式暴露"为什么现在该复习"的原因。
    try:
        forgetting.sync_from_analysis(BASE, normalize=True)   # Phase D-D: 生产启用归一化
        due_items = forgetting.due_cards(BASE, top_n=12)
    except Exception:
        due_items = []
    if due_items:
        def _reason(c):
            # P0-3/UI-E: 状态(已逾期/今日到期)已由上方 badge 表达, 此处仅给
            # 「保持率 + 已复习次数」, 避免 hero/Up-Next 每行重复读「已逾期 N 天」。
            return "保持率 %d%% · 已复习 %d 次" % (c["retention"], c["review_count"])
        hero = due_items[0]
        rest = due_items[1:]
        h_badge = ('<span class="tag">已逾期 %d 天</span>' % hero["overdue_days"]
                   if hero["overdue_days"] > 0 else '<span class="tag">今日到期</span>')
        h_link = (' · <a href="/editor?date=%s">看笔记</a>' % hero["source_date"]) \
            if hero.get("source_date") else ""
        h_qbar = ''.join('<button data-q="%d" title="质量 %d/5 快捷打卡">%d</button>' % (q0, q0, q0)
                         for q0 in range(1, 6))
        due_html = (
            '<div class="next-review-hero">'
            '<div class="nrh-label">🌟 下个复习（最弱优先 · 确定性顺序）</div>'
            '<div class="rec hero"><span class="ricon">🧠</span>'
            '<b class="rcon">%s</b>%s'
            '<span class="rrsn">%s%s</span>'
            '<button class="btn btn-mini" onclick="markReview(this)" data-c="%s"><i class="ni">✅</i>复习打卡</button>'
            '<span class="qbar">%s</span></div>'
            '</div>' % (esc_inline(_clabel(hero["concept"])), h_badge, _reason(hero), h_link,
                        esc_inline(hero["concept"]), h_qbar))
        if rest:
            rows = ""
            for c0 in rest:
                badge = ('<span class="tag">已逾期 %d 天</span>' % c0["overdue_days"]
                         if c0["overdue_days"] > 0 else '<span class="tag">今日到期</span>')
                link = (' · <a href="/editor?date=%s">看笔记</a>' % c0["source_date"]) \
                    if c0.get("source_date") else ""
                qbar_html = ''.join('<button data-q="%d" title="质量 %d/5 快捷打卡">%d</button>' % (q0, q0, q0)
                                    for q0 in range(1, 6))
                rows += ('<div class="rec upnext"><span class="ricon">🧠</span>'
                         '<b class="rcon">%s</b>%s'
                         '<span class="rrsn">%s%s</span>'
                         '<button class="btn btn-mini" onclick="markReview(this)" data-c="%s"><i class="ni">✅</i>复习</button>'
                         '<span class="qbar">%s</span></div>'
                         % (esc_inline(_clabel(c0["concept"])), badge, _reason(c0), link,
                            esc_inline(c0["concept"]), qbar_html))
            due_html += ('<div class="upnext-wrap"><div class="nrh-label">⬇️ 接下来（共 %d 个）</div>%s</div>'
                         % (len(rest), rows))
        due_html += "<p class='dim' style='margin-top:6px'>共 <b>%d</b> 个概念到期待复习——先复习，再开新内容</p>" % len(due_items)
    else:
        due_html = empty_block("check", "✨ 今天没有到期的知识点——写笔记后自动进入遗忘曲线")
    # P0-2: 记忆衰减面板改为"保持率全景"——聚合健康分布(绿/黄/红) + 全量保持率列表,
    #       与"复习中心"(仅到期待办)形成"观察 vs 行动"互补, 消除原 83% 概念重复。
    try:
        decay_rows_v = forgetting.decay_rows(BASE, top_n=20)
    except Exception:
        decay_rows_v = []
    if decay_rows_v:
        green = sum(1 for r1 in decay_rows_v if r1["retention"] >= 70)
        yellow = sum(1 for r1 in decay_rows_v if 40 <= r1["retention"] < 70)
        red = sum(1 for r1 in decay_rows_v if r1["retention"] < 40)
        summary = ('<div class="decay-summary">'
                   '<span class="dstat green">🟢 稳固 %d</span>'
                   '<span class="dstat yellow">🟡 留意 %d</span>'
                   '<span class="dstat red">🔴 危急 %d</span>'
                   '</div>' % (green, yellow, red))
        bars = "".join(
            "<div class='decay'><span class='dname'>%s</span>"
            "<div class='dbar'><div class='dfill' style='width:%d%%;background:%s'></div></div>"
            "<span class='dpct'>%d%%</span></div>"
            % (esc_inline(_clabel(r1["concept"])), r1["retention"], _ret_color(r1["retention"]),
               r1["retention"])
            for r1 in decay_rows_v)
        decay_html = (summary + bars +
                      "<p class='dim'>配色: 绿 ≥70 ｜ 黄 40~69 ｜ 红 &lt;40 —— 整体保持率分布;"
                      "危急项已并入「复习中心」按最弱优先处理</p>")
    else:
        decay_html = empty_block("sprout", "暂无知识档案——保存一篇笔记，这里就会长出你的记忆花园")
    try:
        # UI-003: 先滤掉工程测试产物(test_report_*), 再取前 8 条 —— 面板只呈现真实学习报告
        rep_ls = [r2 for r2 in reportio.list_reports(BASE)
                  if not str(r2.get("name", "")).startswith("test_report_")][:8]
    except Exception:
        rep_ls = []
    if rep_ls:
        rep_html = "".join(
            "<a class='rvtag' href='#' onclick=\"openReport('%s');return false\">📄 %s</a>&nbsp;"
            % (r2["name"], esc_inline(r2["name"])) for r2 in rep_ls)
        rep_html += ("<p class='dim' style='margin-top:6px'>点击在线预览；"
                     "每周一/每月首日启动时自动生成当期报告</p>")
    else:
        rep_html = empty_block("doc", "还没有报告——下次启动自动生成周报与月报")

    # v1.2 学习节奏自适应: 引擎预测 × 自适应系数(参数存 settings.adaptive, 设置页可调)
    cfg_ad = settings.load_settings(BASE).get("adaptive", {})
    ad = adaptive.evaluate(adaptive.recent_rates(st), cfg_ad)
    adj_pred = adaptive.apply_factor(tm["predicted"], ad["factor"])
    ad_badge = ""
    if ad["state"] == "boost":
        # PENDING: [UI-Refactor-Phase5a] 背景 #1f3a2a 为不透明成功画布色, 非 --color-state-success-soft(透明), 保留固定值
        ad_badge = (' <span class="tag" style="background:#1f3a2a;color:#a6e3a1">'
                    '⚡ 次日可加量：%s</span>' % esc_inline(ad["reason"]))
    elif ad["state"] == "ease":
        # PENDING: [UI-Refactor-Phase5a] 背景 rgba(210,153,34,.12) 色相与 --warn(#F2994A) 不同, 映射会改色, 保留
        ad_badge = (' <span class="tag" style="background:rgba(210,153,34,.12);color:var(--color-state-warning)">'
                    '🛟 %s</span>' % esc_inline(ad["reason"]))
    # planline 重算: 与上方原始分支同构, 但预测数换成自适应后的值并附徽标
    if fat.get("active"):
        planline = ('<span class="bad">🔥 疲劳模式（%s）</span> · 明日建议 <b>%d</b> 条%s'
                    % (esc_inline(fat.get("reason", "")), adj_pred, ad_badge))
    else:
        planline = ('<span class="good">✅ 状态良好</span> · 明日建议 <b>%d</b> 条（7日均 %.1f 条）%s'
                    % (adj_pred, tm["avg7_done"], ad_badge))
    if ad.get("rest_hint"):
        rec_html = ("<div class='rec'><span class='ricon'>💤</span>"
                    "<b class='rcon'>休整建议</b><span class='rrsn'>"
                    + esc_inline(ad["reason"]) +
                    "——今天少排一点，恢复节奏优先；也可在设置页调整自适应参数</span></div>") + rec_html
    try:
        weak_items = mastery.weak_concepts(BASE, top_n=5)
    except Exception:
        weak_items = []
    if weak_items:
        due_html += ("<p style='margin-top:10px'><b>🎯 重点攻克队列</b>"
                     "（掌握分&lt;40 自动入围，周日会自动排入下周专项练习）：<br>"
                     # 源码即真相: .tag 主题 !important 强制 tag-bg/pink, 内联原 #3b2f3d/#EB5757 被覆盖; 此处对齐同值语义 token
                     + "".join("<span class='tag' style='background:var(--color-surface-tag);color:var(--color-text-on-tag);"
                               "margin:3px 4px 0 0'>%s · %d分</span>"
                               % (esc_inline(_clabel(c0)), s0) for c0, s0 in weak_items) + "</p>")

    # v1.3 主题系统: 依据 settings.theme 生成末位覆盖层(变量根+带权重规则)
    theme_css_cur = theme.override_css(theme.current_theme(BASE), target="dashboard")
    guide_done_v = bool(settings.load_settings(BASE).get("guide_done", False))

    # 读取外部 CSS 文件 (解耦: CSS 不再内嵌于 Python 模板字符串)


    return {
        "status": status,
        "roadmap": roadmap,
        "profile": profile,
        "daily": daily,
        "st": st,
        "task_html": task_html,
        "dn": dn,
        "tn": tn,
        "tp": tp,
        "pct": pct,
        "hint": hint,
        "planline": planline,
        "ring": ring,
        "bars": bars,
        "subj_html": subj_html,
        "plan_html": plan_html,
        "milestone_html": milestone_html,
        "review_html": review_html,
        "rec_html": rec_html,
        "rep_html": rep_html,
        "due_html": due_html,
        "decay_html": decay_html,
        "kb": kb,
        "review": review,
    }
