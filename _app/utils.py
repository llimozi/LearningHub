# -*- coding: utf-8 -*-
"""utils.py —— 工具函数（原 build_dashboard.py J 类, Phase 2.1 迁移）。

依赖: config + 标准库, 无内部模块调用。
"""
import re
import datetime
from html import escape as html_escape

from _app import config


def next_day(ds):
    return (datetime.date.fromisoformat(ds) + datetime.timedelta(days=1)).isoformat()


def esc_inline(t):
    t = re.sub(r"&", "&amp;", t)
    t = re.sub(r"<", "&lt;", t)
    t = re.sub(r">", "&gt;", t)
    t = re.sub(r'"', "&quot;", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', t)
    return t


def esc_attr(value):
    """HTML 属性上下文专用转义；quote=True 同时处理单双引号。"""
    return html_escape(str(value), quote=True)


def safe_task(task):
    """清洗导入或磁盘中的任务字段，保证渲染层只接触受控类型。"""
    tid = str(task.get("id", ""))
    if not config._SAFE_TASK_ID_RE.fullmatch(tid):
        # 非法 id 不参与后续交互，但保留可见任务，避免坏数据隐藏整桶计划。
        tid = "invalid-" + re.sub(r"[^A-Za-z0-9_.:-]", "", tid)[:32]

    src_date = str(task.get("src_date", config.TODAY))
    try:
        datetime.date.fromisoformat(src_date)
    except ValueError:
        src_date = config.TODAY

    try:
        priority = max(1, min(3, int(task.get("priority", 2))))
    except (TypeError, ValueError):
        priority = 2

    est_raw = task.get("est_minutes")
    try:
        est_minutes = max(1, min(600, int(est_raw))) if est_raw is not None else None
    except (TypeError, ValueError):
        est_minutes = None

    return {
        "id": tid,
        "text": str(task.get("text", "")),
        "done": bool(task.get("done")),
        "carried": bool(task.get("carried")),
        "defer2": bool(task.get("defer2")),
        "priority": priority,
        "src_date": src_date,
        "est_minutes": est_minutes,
        "done_at": task.get("done_at"),
    }


def md_to_html(md):
    lines = md.splitlines()
    out, i, in_table = [], 0, False
    def ct():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            ct(); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            ct(); lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, esc_inline(m.group(2)), lvl)); i += 1; continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if set(s.replace("|", "")) <= set("-: "):
                i += 1; continue
            if not in_table:
                out.append("<table><tbody>"); in_table = True
                out.append("<tr>" + "".join("<th>%s</th>" % esc_inline(c) for c in cells) + "</tr>")
            else:
                cls = ' class="warn"' if ("⚠️" in "".join(cells) or "❌" in "".join(cells)) else ""
                out.append("<tr%s>" % cls + "".join("<td>%s</td>" % esc_inline(c) for c in cells) + "</tr>")
            i += 1; continue
        ct()
        if s.startswith(">"):
            out.append("<blockquote>%s</blockquote>" % esc_inline(s.lstrip("> ").rstrip(">"))); i += 1; continue
        if re.match(r"^-{3,}$", s):
            out.append("<hr>"); i += 1; continue
        m = re.match(r"^(?:\d+\.|-|\*)\s+(.*)$", s)
        if m:
            out.append("<div class='li'>• %s</div>" % esc_inline(m.group(1))); i += 1; continue
        out.append("<p>%s</p>" % esc_inline(s)); i += 1
    ct()
    return "\n".join(out)


def section(md, title):
    m = re.search(r"^##\s*" + re.escape(title) + r"[^\n]*$", md, re.M)
    if not m:
        return ""
    rest = md[m.end():]
    n = re.search(r"^##\s+", rest, re.M)
    return rest[:n.start()] if n else rest


def _ret_color(p):
    """记忆衰减条配色: 绿≥70 / 黄40~69 / 红<40"""
    try:
        p = int(p)
    except (TypeError, ValueError):
        p = 0
    if p >= 70:
        return "var(--color-state-success)"
    if p >= 40:
        return "var(--color-state-warning)"
    return "var(--color-state-error)"


def empty_block(kind, text):
    """空状态统一容器: 插画 + 引导文案(颜色跟随主题变量)"""
    svg = config.EMPTY_SVG.get(kind, config.EMPTY_SVG["notebook"])
    return ("<div class='empty'>" + svg + "<p>" + text + "</p></div>")


def bar(p, cls="fill prog"):
    try:
        w = max(0, min(100, int(p)))
    except (TypeError, ValueError):
        return ""
    return '<div class="bar"><div class="%s" style="width:%d%%"></div></div>' % (cls, w)


def plan_hint(done_n, total_n):
    if total_n == 0:
        return "今天还没有任务"
    if done_n == 0:
        return "当前 0 勾选 → 收尾将<b>整批顺延</b>到明天"
    if done_n == total_n:
        return "当前全部完成 → 明日<b>无遗留</b>, 正常排新任务"
    return "当前部分完成 → 未勾的 <b>%d 条</b>将带「顺延」标签进入明日计划" % (total_n - done_n)


__all__ = [
    "next_day", "esc_inline", "esc_attr", "safe_task", "md_to_html",
    "section", "_ret_color", "empty_block", "bar", "plan_hint",
]
