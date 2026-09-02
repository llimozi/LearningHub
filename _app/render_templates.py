# -*- coding: utf-8 -*-
"""render_templates.py —— Dashboard HTML 面板模板函数 (D-5b 方案 A)

原则: 「输入数据 → 输出 HTML」纯函数。
  - 无 IO / 无文件访问 / 无业务调用 / 无状态修改 / 无副作用
  - 动态字符串由调用方(renderer 数据层)生成后传入, 本模块不转义(保持原始行为)
依赖方向: renderer.py → render_templates.py (单向, 无循环 import)
"""


def _tpl_heatmap():
    """学习热力图面板(D-5b-1): 纯静态容器, JS 动态填充 #hm。
    DOM 契约: #pnl-heatmap > .hmwrap > #hm (dashboard.js getElementById('hm'))"""
    return ('    <div class="card s12" id="pnl-heatmap">\n'
            '      <h2><i class="ni">🔥</i>学习热力图（近 365 天）</h2>\n'
            '      <div class="hmwrap"><div id="hm" class="dim">热力图加载中…</div></div>\n'
            '    </div>')


def _tpl_decay(decay_html):
    """记忆保持率全景面板(D-5b-1): __DECAY__ placeholder 参数化。
    decay_html 由 renderer 数据层生成(含 HTML 片段), 本函数只做插入。
    P0-2: 该面板定位为"观察层"(全量保持率分布), 与 pnl-review 的"行动层"互补。"""
    return ('    <div class="card s6" id="pnl-decay">\n'
            '      <h2><i class="ni">📉</i>记忆保持率全景（最弱排最前）</h2>\n'
            '      ' + decay_html + '\n'
            '    </div>')


def _tpl_insight():
    """学习洞察面板(D-5b-2A): 纯静态容器, JS 异步填充 inswrap/slotcard/weekly-narr。"""
    return ('    <div class="card s12" id="pnl-insight">\n'
            '      <div class="cardhead"><h2><i class="ni">📊</i>学习洞察</h2><span class="dim">认知负荷 · 知识稳固度 · 专注时段</span></div>\n'
            '      <div id="inswrap"><p class="dim">洞察计算中…</p></div>\n'
            '      <div id="slotcard" class="suggestcard" style="display:none"></div>\n'
            '      <details id="weekly-narr" class="narr">\n'
            '        <summary>📋 本周叙事周报(点击展开)</summary>\n'
            '        <div id="narr-body" class="dim mt6">展开时自动生成…</div>\n'
            '        <button class="btn btn-mini btn-ghost" id="narr-copy" style="margin-top:8px">📋 复制 Markdown</button>\n'
            '      </details>\n'
            '    </div>')


def _tpl_review(due_html, review_html):
    """复习中心面板(D-5b-2A): __DUE__/__REVIEW__ 参数化。"""
    return ('    <div class="card s6" id="pnl-review">\n'
            '      <h2><i class="ni">🧠</i>复习中心（遗忘曲线优先）</h2>\n'
            '      ' + due_html + '\n'
            '      <div class="planline"><b>语义分析队列</b>（保存笔记后自动生成）</div>\n'
            '      ' + review_html + '\n'
            '    </div>')


def _tpl_progress(subj_html, streak, next_review):
    """科目进度面板(D-5b-2A): __SUBJ__/__STREAK__/__NEXT_REVIEW__ 参数化。
    streak 由 renderer 数据层传入(side 面板仍由 replace 消费同一值)。"""
    return ('    <div class="card s6" id="pnl-progress">\n'
            '      <h2><i class="ni">📚</i>科目进度与节奏</h2>\n'
            '      ' + subj_html + '\n'
            '      <div class="planline">连续打卡 <span class="kpi">🔥 ' + streak + ' 天</span> &nbsp;·&nbsp; 下次复习 <b>📅 ' + next_review + '</b></div>\n'
            '    </div>')


def _tpl_milestone(week, milestone_html, reviewq_html):
    """里程碑面板(D-5b-2A): __WEEK__/__MILESTONE__/__REVIEWQ__ 参数化。"""
    return ('    <div class="card s6" id="pnl-milestone">\n'
            '      <h2><i class="ni">🏁</i>本周里程碑（阶段总览）</h2>\n'
            '      <div class="mt6">本周重点：<b>' + week + '</b></div>\n'
            '      ' + milestone_html + '\n'
            '      ' + reviewq_html + '\n'
            '    </div>')


def _tpl_plan(plan_html):
    """四线并行计划面板(2026-09-01 新增, 内容型, 复用既有 .subj/.bar/.tag 组件)。

    说明: 标题刻意不用 <i class="ni"> —— 新增 mask 规则会破坏 icon_contract
    备案计数(31), 且 CSS 注释明确"未匹配面板的 .ni 会无图标"; 裸 h2 是官方降级路径。
    展示: 当前绝对优先横幅 + 每线(代号/名称/阶段 tag/总进度条/目标/里程碑倒计时/建议时长)。
    """
    return ('    <div class="card s12" id="pnl-plan">\n'
            '      <h2>学习计划 · 四线并行</h2>\n'
            '      <div class="sub" style="margin-bottom:8px">总纲：学习总计划_四线并行.md</div>\n'
            + (plan_html or '<p class="dim">plan.json 未配置（或暂无四线数据）</p>') +
            '\n    </div>')


def _tpl_kb(kb_html):
    """知识库面板(D-5b-2A): __KB__ 参数化。"""
    return ('    <div class="card s6" id="pnl-kb">\n'
            '      <h2><i class="ni">📒</i>知识库（daily 笔记 · 按标签聚合）</h2>\n'
            '      ' + kb_html + '\n'
            '    </div>')


def _tpl_setcard():
    """设置面板(D-5b-2A): 纯静态容器, JS 异步填充 #setcard。"""
    return ('    <div class="card s6" id="setcard-wrap" data-panel="settings">\n'
            '      <h2><i class="ni">⚙️</i>设置</h2>\n'
            '      <div id="setcard"><p class="dim">设置加载中…</p></div>\n'
            '    </div>')


def _tpl_overview(pct, mainbar_html, ring_html, dn, tn, bars_html, planline_html):
    """总览面板(D-5b-2B): 7 个 placeholder 参数化, DN/TN 跨面板显式传递。"""
    return ('    <div class="card s12" id="pnl-overview">\n'
            '      <h2><i class="ni">📈</i>总览</h2>\n'
            '      <div class="ovgrid">\n'
            '        <div>\n'
            '          <div class="big">' + pct + '<small>%</small></div>\n'
            '          <div class="ovlab dim">总进度（里程碑口径）</div>\n'
            '          ' + mainbar_html + '\n'
            '          <div class="mchain">\n'
            '            <span class="mstep">W0 收尾</span><i>→</i><span class="mstep">记忆</span><i>→</i><span class="mstep">RAG</span><i>→</i><span class="mstep">MCP</span><i>→</i><span class="mstep">编排</span><i>→</i><span class="mstep">桌面化</span><span class="mtag">10-17 验收</span>\n'
            '          </div>\n'
            '        </div>\n'
            '        <div class="ovdiv"></div>\n'
            '        <div style="text-align:center">\n'
            '          <div class="ringbox">' + ring_html + '<div class="ringcenter" id="ringcnt">' + dn + '/' + tn + '</div></div>\n'
            '          <div class="ovlab dim">今日任务完成</div>\n'
            '        </div>\n'
            '        <div class="ovdiv"></div>\n'
            '        <div>\n'
            '          <div class="bars">' + bars_html + '</div>\n'
            '          <div class="ovlab dim">近 7 天完成数趋势</div>\n'
            '          <div class="planline">' + planline_html + ' <span class="dim">· 右键任务可设优先级</span></div>\n'
            '        </div>\n'
            '      </div>\n'
            '    </div>')


def _tpl_tasks(task_html, daily_html):
    """今日任务面板(D-5b-2B): __TASKS__/__DAILY__ 参数化; JS 依赖 btn-batchmode/reducemode 等 id 保持。"""
    return ('    <div class="card s8" id="pnl-tasks">\n'
            '      <div class="cardhead"><h2><i class="ni">🎯</i>今日任务</h2><span class="dim">点击勾选 · 右键更多操作</span></div>\n'
            '      <div class="cardtools">\n'
            '        <button class="btn btn-mini btn-ghost" id="btn-batchmode" style="margin-top:0" title="批量整理模式:开启后单击行=选中,底部出现操作栏"><i class="ni">☑</i>批量模式</button>\n'
            '        <button class="btn btn-mini btn-ghost" id="btn-cmdk-top" style="margin-top:0" title="命令面板 (Ctrl+P)">⌘ 命令面板</button>\n'
            '        <span class="dim batchhint" style="display:none;font-size:11px">批量中: 单击行选择, Shift 可多选</span>\n'
            '        <button class="btn btn-mini btn-ghost" id="btn-backfill" style="margin-top:0" title="为已完成但没有时刻记录的任务补录 done_at(洞察面板依赖它)"><i class="ni">🕐</i>补记完成时刻</button>\n'
            '        <span id="backfill-hint" class="dim" style="font-size:11px"></span>\n'
            '      </div>\n'
            '      <div id="reducemode" class="reducemode" style="display:none">\n'
            '        <b>🛡️ 减负模式</b>\n'
            '        <span class="dim">检测到认知负荷过载——开启后隐藏 P3 低优任务、到期复习软推迟 3 天(次日自动解除)</span>\n'
            '        <button class="btn btn-mini" id="red-on" style="margin-top:0;background:var(--color-state-warning)">开启保护</button>\n'
            '      </div>\n'
            '      ' + task_html + '\n'
            '      <details><summary>今日日志原文</summary>' + daily_html + '</details>\n'
            '    </div>')


def _tpl_today(tp, tpw, dn, tn, hint_html, rollover_btn_html):
    """今日完成度面板(D-5b-2B, UI-005 收缩): 完成度唯一图形表达在 #pnl-overview 环;
    本卡保留 #taskcnt(跨面板 DN/TN 契约)+明日规划+收尾入口。tp/tpw 参数保留以兼容调用点。"""
    return ('    <div class="card s4" id="pnl-today">\n'
            '      <h2><i class="ni">✅</i>今日完成度</h2>\n'
            '      <div class="sub" id="taskcnt">' + dn + ' / ' + tn + ' 条</div>\n'
            '      <div class="sub mt6">明日规划：' + hint_html + '</div>\n'
            '      ' + rollover_btn_html + '\n'
            '    </div>')


def _tpl_help():
    """帮助面板(D-5b-2C): 纯静态, 无 placeholder。
    onclick Contract: openHelp() 调 dashboard.js 顶层全局函数。"""
    return ('    <div class="card s6" id="pnl-help">\n'
            '      <h2><i class="ni">❓</i>帮助（内置）</h2>\n'
            '      <div style="display:flex;gap:10px;flex-wrap:wrap">\n'
            '        <button class="btn" style="margin-top:0" onclick="openHelp()"><i class="ni">📖</i>打开使用帮助</button>\n'
            '        <span class="dim" style="align-self:center;font-size:12px">快捷键一览 · 功能说明 · FAQ · 数据备份指引</span>\n'
            '      </div>\n'
            '    </div>')


def _tpl_foot(roadmap_html, profile_html):
    """页脚(D-5b-3A): __ROADMAP__/__PROFILE__ 参数化。"""
    return ('  <div class="foot">\n'
            '    <details><summary>展开：总路线图 ROADMAP 全文</summary>' + roadmap_html + '</details>\n'
            '    <details class="mt6"><summary>展开：学习档案 PROFILE 全文</summary>' + profile_html + '</details>\n'
            '    <p class="dim mt14">LearningHub 本地仪表盘 · 规划引擎 planner.py · 数据全部保存在本机，不上传任何服务器</p>\n'
            '  </div>')


def _tpl_ctxmenu():
    """右键菜单(D-5b-3A): 纯静态, onclick setpri 全局函数。"""
    return ('<div id="ctxmenu" class="ctx">\n'
            '  <div onclick="setpri(1)">🔴 P1 高优（疲劳期保留）</div>\n'
            '  <div onclick="setpri(2)">🟡 P2 中优（默认）</div>\n'
            '  <div onclick="setpri(3)">🔵 P3 低优（疲劳期丢弃）</div>\n'
            '</div>')


def _tpl_keyhelp():
    """快捷键面板(D-5b-3A): 纯静态, onclick 内联关闭。"""
    return ('<div id="keyhelp" class="guidewrap"><div class="gcard" style="text-align:left;max-width:520px">\n'
            '  <h3 style="margin-bottom:10px">⌨️ 键盘快捷键</h3>\n'
            '  <div class="li">Ctrl+P 命令面板 · Ctrl+N 快速捕获 · Ctrl+K 全文搜索</div>\n'
            '  <div class="li">Ctrl+1~4 跳转面板 · Ctrl+R 刷新 · Ctrl+Z 撤销上一步</div>\n'
            '  <div class="li">↑↓ 或 J/K 选任务 · Space/D 勾选 · E 详情 · S 顺延一天</div>\n'
            '  <div class="li">Delete 删除 · 1/2/3 设优先级 · ? 本帮助 · Esc 关闭浮层</div>\n'
            '  <p class="dim mt6" style="cursor:pointer;text-align:center" onclick="document.getElementById(\'keyhelp\').style.display=\'none\'">关闭 (Esc)</p>\n'
            '</div></div>')


def _tpl_snomenu():
    """排序菜单(D-5b-3A): 纯静态, onclick snoPick 全局函数。"""
    return ('<div id="snomenu" class="ctx" style="display:none">\n'
            '  <div onclick="snoPick(1)">⏭ 顺延 1 天</div>\n'
            '  <div onclick="snoPick(3)">⏭ 顺延 3 天</div>\n'
            '  <div onclick="snoPick(7)">⏭ 下周再说</div>\n'
            '</div>')


def _tpl_ksearch():
    """搜索浮层(D-5b-3B): 纯静态, JS 填充 ksres。"""
    return ('<div id="ksearch" class="ksearch">\n'
            '  <div class="ksbox">\n'
            '    <input id="ksinput" placeholder="搜索任务 / 笔记 / 知识点 / 标签…" autocomplete="off">\n'
            '    <div id="ksres"><div class="kshint" style="border:none">输入关键词开始检索（支持中文子串）</div></div>\n'
            '    <div class="kshint">Enter 打开第一条 · Esc 关闭</div>\n'
            '  </div>\n'
            '</div>')


def _tpl_guide():
    """引导浮层(D-5b-3B): 纯静态, onclick guideStep/guideNext/guideFinish 全局函数。"""
    return ('<div id="guide" class="guidewrap">\n'
            '  <div class="gcard">\n'
            '    <div class="gestep">📊</div>\n'
            '    <h3 id="gt">欢迎使用学习仪表盘</h3>\n'
            '    <p class="gdesc" id="gd"></p>\n'
            '    <input id="gdir" class="gdir" placeholder="学习方向，如：AI Agent 开发"\n'
            '           style="display:none;width:90%;background:var(--color-surface-input);color:var(--color-text-primary);\n'
            '                  border:1px solid var(--color-border-strong);border-radius:8px;padding:7px 10px;\n'
            '                  font-size:13px;margin-bottom:4px">\n'
            '    <div class="gdots" id="gdots"></div>\n'
            '    <div style="display:flex;gap:10px;justify-content:center;margin-top:6px">\n'
            '      <button class="btn btn-ghost" style="margin-top:0" id="gprev" onclick="guideStep(-1)">上一步</button>\n'
            '      <button class="btn" style="margin-top:0" id="gnext" onclick="guideNext()">下一步</button>\n'
            '    </div>\n'
            '    <p class="dim" style="margin-top:8px;font-size:11px;cursor:pointer" onclick="guideFinish()">跳过引导</p>\n'
            '  </div>\n'
            '</div>')


def _tpl_cmdk():
    """命令面板浮层(D-5b-3B): 纯静态, JS 填充 cmdk-res。"""
    return ('<div id="cmdk" class="cmdkwrap">\n'
            '  <div class="cmdkbox">\n'
            '    <input id="cmdk-input" placeholder="搜索任务 / #标签 / @笔记, 或输入 > 执行命令… (Esc 关闭)" autocomplete="off">\n'
            '    <div id="cmdk-res"></div>\n'
            '    <div class="kshint">↑↓ 导航 · Enter 执行 · Esc 关闭 · #标签 @笔记 &gt;命令</div>\n'
            '  </div>\n'
            '</div>')


def _tpl_dtpick():
    """补记时刻浮层(D-5b-3B): 纯静态(原样保留 dtpick 起始标签形态)。"""
    return ('<div id="dtpick" class="guidewrap"\n'
            '  <div class="gcard">\n'
            '    <h3>🕐 补记完成时刻</h3>\n'
            '    <p class="gdesc" id="dt-desc">将把该时刻写入所选任务的 done_at</p>\n'
            '    <input type="datetime-local" id="dt-input" class="dt-input">\n'
            '    <input type="number" min="1" max="600" id="dt-actual" class="dt-input" placeholder="实际耗时(分钟, 可选)">\n'
            '    <div style="display:flex;gap:10px;justify-content:center;margin-top:12px">\n'
            '      <button class="btn btn-ghost" style="margin-top:0" id="dt-cancel">取消</button>\n'
            '      <button class="btn" style="margin-top:0" id="dt-apply">应用</button>\n'
            '    </div>\n'
            '    <p class="dim" style="margin-top:8px;font-size:11px">专注时段指标依赖真实完成时刻——随手补录,洞察更准</p>\n'
            '  </div>\n'
            '</div>')


def _tpl_head(css, themecss, today, interactive=True):
    """head(D-5b-3C, D-8-1 双模式): interactive 外链 dashboard.css, snapshot 内联自包含。
    顺序契约: CSS 源(link/varroot)必须位于 themecss 主题覆盖层之前。"""
    css_tag = ('<link rel="stylesheet" href="/dashboard.css">' if interactive
               else '<style id="varroot">' + css + '</style>')
    return ('<!DOCTYPE html>\n' + '<html lang="zh"><head><meta charset="utf-8">\n' + '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + '<title>学习仪表盘 · ' + today + '</title>\n' + css_tag + '\n' + '<style id="themecss">' + themecss + '</style></head>\n')

def _tpl_side(streak):
    """side(D-5b-3C): 原样提取。"""
    return ('<aside class="side">\n' + '  <div class="brand">📊 <b>LearningHub</b></div>\n' + '  <nav class="nav">\n' + '    <a href="#pnl-overview" class="on"><i class="ni">📈</i>总览与进度</a>\n' + '    <a href="#pnl-tasks"><i class="ni">🎯</i>今日任务</a>\n' + '    <a href="#pnl-heatmap"><i class="ni">🔥</i>学习热力图</a>\n' + '    <a href="#pnl-review"><i class="ni">🧠</i>复习中心</a>\n' + '    <a href="#pnl-graph"><i class="ni">🕸️</i>知识图谱</a>\n' + '    <a href="#pnl-rec"><i class="ni">✨</i>推荐与报告</a>\n' + '    <a href="#pnl-progress"><i class="ni">📚</i>进度与知识库</a>\n' + '    <a href="#setcard-wrap"><i class="ni">⚙️</i>设置与帮助</a>\n' + '  </nav>\n' + '  <div class="sidefoot">\n' + '    <div class="kpi">🔥 ' + streak + ' 天</div>\n' + '    <div class="sub mt6">连续打卡</div>\n' + '    <div class="dim mt10">仅本机 127.0.0.1<br>关闭 bat 窗口即停止服务</div>\n' + '  </div>\n' + '</aside>\n')

def _tpl_topbar(today, day, total, deadline, now):
    """topbar(D-5b-3C): 原样提取。"""
    return ('  <header class="topbar">\n' + '    <div>\n' + '      <h1>学习仪表盘 · ' + today + '</h1>\n' + '      <div class="sub">第 ' + day + '/' + total + ' 天 · 截止 ' + deadline + '</div>\n' + '    </div>\n' + '    <span class="clock">🕒 ' + now + '</span>\n' + '    <button id="btn-capture" class="btn" style="margin-top:0" title="自然语言快速捕获 (Ctrl+N)"><i class="ni">➕</i>快捕</button>\n' + '    <div id="quickbar" class="quickbar" style="display:none">\n' + '      <input id="qc-input" class="qc-input" placeholder="想到就写: 明天上午 45分钟 复习agent · Enter 创建">\n' + '    </div>\n' + '    <span class="tspacer"></span>\n' + '    <button class="btn-ghost" id="btn-note" style="margin-top:0" onclick="window.open(\'/editor\')"><i class="ni">📝</i>写笔记</button>\n' + '    <span id="redbadge" class="redbadge" style="display:none" title="减负进行中:点击关闭"><i class="ni">🛡️</i>减负中</span>\n' + '    <button id="daily-focus" class="dailyfoc" style="display:none" title="今日焦点——点击跳转对应面板">\n' + '      <span id="df-icon"></span><span id="df-text"></span>\n' + '      <span id="df-close" title="今日隐藏(明天恢复)" onclick="event.stopPropagation();this.parentNode.style.display=\'none\'">✕</span>\n' + '    </button>\n' + '    <button class="btn-good" id="btnweek" style="margin-top:0" title="每周日自动呼吸灯提醒" onclick="weeklyReport()"><i class="ni">🔄</i>生成周报</button>\n' + '  </header>\n')

def _tpl_batchbar():
    """batchbar(D-5b-3C): 原样提取。"""
    return ('<div id="batchbar" class="batchbar">\n' + '  <b>已选 <span id="selcnt">0</span> 条：</b>\n' + '  <button class="btn btn-mini" onclick="batchDo(\'done\',true)">✅ 完成</button>\n' + '  <button class="btn btn-mini" style="background:var(--color-state-error)" onclick="batchDo(\'delete\')">🗑 删除</button>\n' + '  <button class="btn btn-mini" onclick="batchDo(\'priority\',1)">P1</button>\n' + '  <button class="btn btn-mini" style="background:var(--color-state-warning)" onclick="batchDo(\'priority\',2)">P2</button>\n' + '  <button class="btn btn-mini" style="background:var(--color-surface-btn-neutral);color:var(--color-on-accent)" onclick="batchDo(\'priority\',3)">P3</button>\n' + '  <button class="btn btn-mini" style="background:var(--color-surface-btn-dimmed);color:var(--color-on-btn-dimmed)" onclick="clearSel()">取消</button>\n' + '</div>\n')

def _tpl_modal():
    """modal(D-5b-3C): 原样提取。"""
    return ('<div id="modal" class="modalwrap" onclick="if(event.target===this)this.style.display=\'none\'">\n' + '  <div class="modal">\n' + '    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">\n' + '      <b id="mtitle">周报</b>\n' + '      <span style="display:flex;gap:8px">\n' + '        <button id="mcopy" class="btn" style="margin:0" onclick="copyReport()">📋 复制 Markdown</button>\n' + '        <button class="btn btn-ghost" style="margin:0" onclick="document.getElementById(\'modal\').style.display=\'none\'">关闭</button>\n' + '      </span>\n' + '    </div>\n' + '    <div id="mbody" class="mdbody dim">…</div>\n' + '  </div>\n' + '</div>\n')


def _tpl_graph():
    """知识图谱面板(D-5d): 纯静态容器, JS 动态填充 gstats/kgwrap。"""
    return ('    <div class="card s12" id="pnl-graph">\n'
            '      <h2><i class="ni">🕸️</i>知识图谱（知识点关联网络）</h2>\n'
            '      <div id="gstats" class="sub" style="margin-bottom:8px">加载中…</div>\n'
            '      <div class="hmwrap"><div id="kgwrap"><p class="dim">加载中…</p></div></div>\n'
            '    </div>')


def _tpl_rec(rec_html):
    """学习推荐面板(D-5d): __REC__ 参数化。"""
    return ('    <div class="card s6" id="pnl-rec">\n'
            '      <h2><i class="ni">✨</i>学习推荐</h2>\n'
            '      ' + rec_html + '\n'
            '    </div>')


def _tpl_reports(rep_html):
    """报告面板(D-5d): __REPORTS__ 参数化。"""
    return ('    <div class="card s6" id="pnl-reports">\n'
            '      <h2><i class="ni">📄</i>报告（周报 / 月报）</h2>\n'
            '      ' + rep_html + '\n'
            '    </div>')
