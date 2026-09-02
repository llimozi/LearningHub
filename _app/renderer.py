# -*- coding: utf-8 -*-
"""renderer.py —— 渲染层（原 build_dashboard.py render 函数, Phase 2.6 迁移）。

render() 原样搬迁, 仅在函数开头将 _app 内部依赖绑定为局部变量
(config./data./utils./services. 动态访问), 函数体逐字节不变。
外部业务模块(planner/heatmap/...) 顶层 import, 与原模块级引用等价。
"""
import json
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

from _app import config, data, services, utils, render_templates, render_data


def render(interactive):
    # Phase 2.6: _app 内部依赖统一动态绑定(便于测试 patch 数据隔离)
    BASE = config.BASE
    TODAY = config.TODAY
    EMPTY_SVG = config.EMPTY_SVG
    _read_dashboard_css = data._read_dashboard_css
    _read_dashboard_js = data._read_dashboard_js
    _tpl_heatmap = render_templates._tpl_heatmap
    _tpl_decay = render_templates._tpl_decay
    _tpl_insight = render_templates._tpl_insight
    _tpl_review = render_templates._tpl_review
    _tpl_progress = render_templates._tpl_progress
    _tpl_milestone = render_templates._tpl_milestone
    _tpl_plan = render_templates._tpl_plan
    _tpl_kb = render_templates._tpl_kb
    _tpl_setcard = render_templates._tpl_setcard
    _tpl_overview = render_templates._tpl_overview
    _tpl_tasks = render_templates._tpl_tasks
    _tpl_today = render_templates._tpl_today
    _tpl_help = render_templates._tpl_help
    _tpl_foot = render_templates._tpl_foot
    _tpl_ctxmenu = render_templates._tpl_ctxmenu
    _tpl_keyhelp = render_templates._tpl_keyhelp
    _tpl_snomenu = render_templates._tpl_snomenu
    _tpl_ksearch = render_templates._tpl_ksearch
    _tpl_guide = render_templates._tpl_guide
    _tpl_cmdk = render_templates._tpl_cmdk
    _tpl_dtpick = render_templates._tpl_dtpick
    _tpl_head = render_templates._tpl_head
    _tpl_side = render_templates._tpl_side
    _tpl_topbar = render_templates._tpl_topbar
    _tpl_batchbar = render_templates._tpl_batchbar
    _tpl_modal = render_templates._tpl_modal
    _tpl_graph = render_templates._tpl_graph
    _tpl_rec = render_templates._tpl_rec
    _tpl_reports = render_templates._tpl_reports
    md_to_html = utils.md_to_html
    bar = utils.bar
    # D-5c: 数据准备/ViewModel 移至 render_data.build_context(含写盘副作用)
    ctx = render_data.build_context(BASE, TODAY, interactive)
    status = ctx["status"]; roadmap = ctx["roadmap"]; profile = ctx["profile"]
    daily = ctx["daily"]; st = ctx["st"]; task_html = ctx["task_html"]
    dn = ctx["dn"]; tn = ctx["tn"]; tp = ctx["tp"]; pct = ctx["pct"]
    hint = ctx["hint"]; planline = ctx["planline"]; ring = ctx["ring"]
    bars = ctx["bars"]; subj_html = ctx["subj_html"]; milestone_html = ctx["milestone_html"]
    review_html = ctx["review_html"]; review = ctx["review"]
    rec_html = ctx["rec_html"]; rep_html = ctx["rep_html"]; due_html = ctx["due_html"]
    decay_html = ctx["decay_html"]; kb = ctx["kb"]
    plan_html = ctx["plan_html"]

    # v1.3 主题系统: 依据 settings.theme 生成末位覆盖层(变量根+带权重规则)
    theme_css_cur = theme.override_css(theme.current_theme(BASE), target="dashboard")
    guide_done_v = bool(settings.load_settings(BASE).get("guide_done", False))

    # 读取外部 CSS 文件 (解耦: CSS 不再内嵌于 Python 模板字符串)
    css_content = _read_dashboard_css()
    dash_js = _read_dashboard_js()
    js_loader = ('<script src="/dashboard.js"></script>' if interactive
                 else '<script>' + dash_js + '</script>')

    page = r"""__PNL_HEAD__
<body>
      __PNL_SIDE__

<main class="main">
      __PNL_TOPBAR__

  <div class="dash">

    <section class="section section-today">
      <h2 class="section-title">今天</h2>
      __PNL_TODAY__
      __PNL_TASKS__
      __PNL_OVERVIEW__
    </section>

    <section class="section section-memory">
      <h2 class="section-title">记忆与复习</h2>
      __PNL_REVIEW__
      __PNL_DECAY__
    </section>

    <section class="section section-progress">
      <h2 class="section-title">进度与洞察</h2>
      __PNL_INSIGHT__
      __PNL_HEATMAP__
      __PNL_GRAPH__
      __PNL_REC__
      __PNL_REPORTS__
      __PNL_PROGRESS__
      __PNL_MILESTONE__
      __PNL_PLAN__
    </section>

    <section class="section section-knowledge">
      <h2 class="section-title">知识与资源</h2>
      __PNL_KB__
      __PNL_SETCARD__
      __PNL_HELP__
    </section>

  </div><!-- /.dash -->

      __PNL_FOOT__
</main>

      __PNL_BATCHBAR__
      __PNL_KSEARCH__
      __PNL_GUIDE__
      __PNL_CTXMENU__
      __PNL_CMDK__
      __PNL_KEYHELP__
      __PNL_SNOMENU__
      __PNL_DTPICK__
<div id="lhtoast"></div>
      __PNL_MODAL__
<script>
window.LH_CONFIG = {graphEmpty: __GRAPH_EMPTY_JSON__, guideDone: __GUIDEDONE_JSON__};
</script>
__JS_LOADER__
</body></html>"""

    btn = '<button class="btn" onclick="rollover()">立即收尾 · 生成明日计划</button>' if interactive else ""
    daily_html = md_to_html(daily) if daily else "<p class='dim'>今天还没有日志</p>"
    page = (page
            .replace("__PNL_HEATMAP__", _tpl_heatmap())
            .replace("__PNL_DECAY__", _tpl_decay(decay_html))
            .replace("__PNL_INSIGHT__", _tpl_insight())
            .replace("__PNL_REVIEW__", _tpl_review(due_html, review))
            .replace("__PNL_PROGRESS__", _tpl_progress(subj_html, str(status.get("streak", "-")), str(status.get("next_review", "-"))))
            .replace("__PNL_MILESTONE__", _tpl_milestone(str(status.get("current_week", "-")), milestone_html, ("<h2 style='margin-top:14px'>复习队列</h2>" + review_html) if review_html else ""))
            .replace("__PNL_PLAN__", _tpl_plan(plan_html))
            .replace("__PNL_KB__", _tpl_kb(kb))
            .replace("__PNL_SETCARD__", _tpl_setcard())
            .replace("__PNL_OVERVIEW__", _tpl_overview(str(pct), bar(pct if isinstance(pct, int) else 0, "fill main"), ring, str(dn), str(tn), bars, planline))
            .replace("__PNL_TASKS__", _tpl_tasks(task_html, daily_html))
            .replace("__PNL_TODAY__", _tpl_today(str(tp), str(tp), str(dn), str(tn), hint, btn))
            .replace("__PNL_HELP__", _tpl_help())
            .replace("__PNL_CTXMENU__", _tpl_ctxmenu())
            .replace("__PNL_KEYHELP__", _tpl_keyhelp())
            .replace("__PNL_SNOMENU__", _tpl_snomenu())
            .replace("__PNL_KSEARCH__", _tpl_ksearch())
            .replace("__PNL_GUIDE__", _tpl_guide())
            .replace("__PNL_CMDK__", _tpl_cmdk())
            .replace("__PNL_DTPICK__", _tpl_dtpick())
            .replace("__PNL_GRAPH__", _tpl_graph())
            .replace("__PNL_REC__", _tpl_rec(rec_html))
            .replace("__PNL_REPORTS__", _tpl_reports(rep_html))
            .replace("__PNL_HEAD__", _tpl_head(css_content, theme_css_cur, TODAY, interactive))
            .replace("__PNL_SIDE__", _tpl_side(str(status.get("streak", "-"))))
            .replace("__PNL_TOPBAR__", _tpl_topbar(TODAY, str(status.get("day", "?")), str(status.get("total_days", "?")), str(status.get("deadline", "-")), datetime.datetime.now().strftime("%H:%M:%S")))
            .replace("__PNL_BATCHBAR__", _tpl_batchbar())
            .replace("__PNL_MODAL__", _tpl_modal())
            .replace("__GRAPH_EMPTY_JSON__", json.dumps(EMPTY_SVG["graph"]))
            .replace("__GUIDEDONE_JSON__", json.dumps(guide_done_v))
            .replace("__JS_LOADER__", js_loader)
            .replace("__PNL_FOOT__", _tpl_foot(md_to_html(roadmap), md_to_html(profile))))
    return page


__all__ = ["render"]
