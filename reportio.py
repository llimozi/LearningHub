# -*- coding: utf-8 -*-
r"""reportio.py —— 周报 / 月报生成器 (v1.1 · 纯标准库, SVG 手绘零依赖)

产物落盘 reports\:
  weekly_YYYYMMDD.md    文件名日期 = 该 ISO 周的周一(周三补看也归到同一份)
  monthly_YYYY-MM.md    月报正文
  trend_YYYY-MM.svg     月报配套四周趋势折线(手绘 SVG, 深色主题配色)

周报四要素(v1.1 规格): 本周完成任务数 / 新增知识点 / 复习次数 / 学习天数热力 + 下周建议。
数据源: tasks.json(history 7日窗口) + daily/knowledge.json(first_seen 与 last_review_ts)
       + daily 笔记字数(heatmap.scan_daily) + recommender.get_recommendations(下周建议)。

ensure_reports: 启动时调用——当周/当月的报告不存在才生成(幂等, 已存在零写盘);
报告是可再生资产, 不进自动备份(backup.py 已排除)。

公开 API:
  build_weekly_markdown(dir, today=None)  -> str
  build_monthly_markdown(dir, today=None) -> (md, svg)
  save_weekly(dir, today=None) / save_monthly(dir, today=None) -> 路径(元组)
  ensure_reports(dir, today=None) -> {created: [...], weekly, monthly}
  list_reports(dir) -> [{name, mtime}] (新→旧)
  read_report(dir, name) -> str | None   # 拒绝路径穿越
"""
import os
import re
import json
import logging
import datetime

import heatmap
import planner

REPORTS_DIR = "reports"


def _rdir(learning_dir):
    return os.path.join(learning_dir, REPORTS_DIR)


def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


# ---------------- 周报 ----------------
def _week_window(today, days=7):
    """近 days 天窗口(含今天), 返回 (起始date, 结束date=today, [逐日date])"""
    start = today - datetime.timedelta(days=days - 1)
    seq = [start + datetime.timedelta(days=i) for i in range(days)]
    return start, today, seq


def build_weekly_markdown(learning_dir, today=None):
    today = today or datetime.date.today()
    start, end, seq = _week_window(today)
    st = _load(os.path.join(learning_dir, "tasks.json"), {}) or {}

    # ---- 一、任务完成 ----
    hist = {h.get("date"): h for h in st.get("history", []) if isinstance(h, dict)}
    done_total = hit_days = 0
    lines = []
    for d in seq:
        ds = d.isoformat()
        h = hist.get(ds)
        if h:
            dn, tt = int(h.get("done", 0)), int(h.get("total", 0))
            mark = "✅" if tt and dn >= tt else ("▫" if dn else "·")
            lines.append("%s %s %d/%d" % (ds[5:], mark, dn, tt))
            done_total += dn
            if tt and dn / tt >= planner.RELEASE_RATE:
                hit_days += 1
        else:
            lines.append("%s · 未收尾" % ds[5:])

    # ---- 二、知识增长 ----
    import forgetting
    kn = forgetting.load_knowledge(learning_dir).get("knowledge", {})
    new_concepts = sorted(c for c, r in kn.items()
                          if _in_window(r.get("first_seen"), start, end))
    # 复习次数 = review_log 流水在窗口内的条数(真实事件数);
    # 旧档案没有流水时降级为「本周有复习动作的知识点数」口径
    reviewed = sum(1 for e in (forgetting.load_knowledge(learning_dir)
                               .get("review_log") or [])
                   if _in_window((e.get("ts") or "")[:10], start, end))
    if not reviewed:
        reviewed = sum(1 for r in kn.values()
                       if _in_window((r.get("last_review_ts") or "")[:10], start, end))

    # ---- 三、学习热力 ----
    daily_notes = heatmap.scan_daily(learning_dir)
    days_map = st.get("days", {})
    heat = []
    for d in seq:
        ds = d.isoformat()
        info = daily_notes.get(ds)
        words = info["chars"] if info else 0
        tasks_n = sum(1 for t in days_map.get(ds, []) if isinstance(t, dict) and t.get("done"))
        blocks = "▓" * min(4, (1 if info else 0) + (1 if tasks_n else 0) +
                           (1 if words >= 100 else 0) + (1 if tasks_n >= 2 else 0)) or "░"
        heat.append("%s %s 笔记%s字/任务%d" % (ds[5:], blocks, words, tasks_n))

    # ---- 四、下周建议(规则引擎, 失败降级占位) ----
    try:
        import recommender
        recs = recommender.get_recommendations(learning_dir, today=today)
        items = recs.get("items", [])
    except Exception:
        items = []
    if items:
        sug = "\n".join("- %s **%s** —— %s" % (_icon(r0.get("type")), r0.get("concept", ""),
                                               r0.get("reason", "")) for r0 in items)
    else:
        sug = "- ✅ 数据积累中或节奏良好，暂无专项建议"

    new_txt = "、".join(new_concepts[:8]) if new_concepts else "暂无"
    return (
        "# 学习周报 · %s ~ %s\n\n" % (start.isoformat(), end.isoformat())
        + "> 生成于 %s · reportio v1.1（本地聚合, 零联网）\n\n" % datetime.datetime.now().isoformat(timespec="seconds")
        + "## 一、任务完成\n"
        + "- 本周完成 **%d** 条 ｜ 达标天数 **%d** 天\n" % (done_total, hit_days)
        + "- 逐日: %s\n\n" % (" ｜ ".join(lines))
        + "## 二、知识增长\n"
        + "- 新增知识点 **%d** 个: %s\n" % (len(new_concepts), new_txt)
        + "- 本周复习 **%d** 次\n\n" % reviewed
        + "## 三、学习热力（近7天）\n"
        + "".join("- %s\n" % h for h in heat) + "\n"
        + "## 四、下周建议（规则引擎实时计算）\n" + sug + "\n")


def _icon(t):
    return {"review": "🔁", "explore": "🔍", "rest": "😴"}.get(t, "•")


def _in_window(date_str, start, end):
    if not date_str:
        return False
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return False
    return start <= d <= end


# ---------------- 月报 ----------------
def _four_week_buckets(today):
    """四个 7 天窗(最老→最新), 返回 [(label, start, end)]"""
    out = []
    for k in range(4):
        end = today - datetime.timedelta(days=7 * (3 - k))
        start = end - datetime.timedelta(days=6)
        out.append((start.strftime("%m-%d"), start, end))
    return out


def build_monthly_markdown(learning_dir, today=None):
    today = today or datetime.date.today()
    st = _load(os.path.join(learning_dir, "tasks.json"), {}) or {}
    hist = {h.get("date"): h for h in st.get("history", []) if isinstance(h, dict)}
    buckets = _four_week_buckets(today)
    values = []
    rows = []
    for label, s, e in buckets:
        done = 0
        d = s
        while d <= e:
            done += int(hist.get(d.isoformat(), {}).get("done", 0))
            d += datetime.timedelta(days=1)
        values.append(done)
        rows.append("- %s ~ %s: 完成 **%d** 条" % (s.isoformat(), e.isoformat(), done))
    svg = _trend_svg([(b[0], v) for b, v in zip(buckets, values)])
    md = ("# 学习月报 · %04d-%02d\n\n" % (today.year, today.month)
          + "> 生成于 %s · reportio v1.1（四周趋势, SVG 手绘零依赖）\n\n" % datetime.datetime.now().isoformat(timespec="seconds")
          + "## 四周趋势\n\n"
          + "![四周趋势](%s)\n\n" % ("trend_%04d-%02d.svg" % (today.year, today.month))
          + "".join(r + "\n" for r in rows) + "\n"
          + "> 折线图配套文件: trend_%04d-%02d.svg（报告预览卡内联展示）\n" % (today.year, today.month))
    return md, svg


def _trend_svg(points, width=560, height=220):
    """手绘四周折线: 深色主题配色; data-values 属性内嵌原始值供测试/前端复用。
    points: [(label, value)] 恰好 4 个, 从左(最老)到右(最新)。"""
    pad_l, pad_r, pad_t, pad_b = 46, 24, 26, 40
    labels = [p[0] for p in points]
    vals = [max(0, int(p[1])) for p in points]
    vmax = max(vals + [1])
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    xs = [pad_l + inner_w * i / (len(points) - 1) for i in range(len(points))]
    ys = [pad_t + inner_h * (1 - v / vmax) for v in vals]
    grid = "".join(
        '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#313244" stroke-width="1"/>'
        % (pad_l, pad_t + inner_h * g / 4, width - pad_r, pad_t + inner_h * g / 4)
        for g in range(5))
    dots = "".join(
        '<circle cx="%.1f" cy="%.1f" r="4" fill="#89b4fa" stroke="#11111b" stroke-width="1.5"/>'
        '<text x="%.1f" y="%.1f" fill="#a6e3a1" font-size="12" text-anchor="middle">%d</text>'
        % (x, y, x, y - 10, v)
        for x, y, v in zip(xs, ys, vals))
    labels_svg = "".join(
        '<text x="%.1f" y="%d" fill="#9399b2" font-size="11" text-anchor="middle">%s</text>'
        % (x, height - 14, lbl) for x, lbl in zip(xs, labels))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" data-values="%s" role="img">'
        '<rect width="100%%" height="100%%" fill="#1e1e2e" rx="10"/>'
        '%s'
        '<polyline points="%s" fill="none" stroke="#89b4fa" stroke-width="2.5" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        '%s%s</svg>'
        % (width, height, width, height,
           " ".join(str(v) for v in vals),
           grid,
           " ".join("%.1f,%.1f" % (x, y) for x, y in zip(xs, ys)),
           dots, labels_svg))


# ---------------- 落盘与读取 ----------------
def save_weekly(learning_dir, today=None):
    today = today or datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    name = "weekly_" + monday.strftime("%Y%m%d") + ".md"
    p = os.path.join(_rdir(learning_dir), name)
    try:
        os.makedirs(_rdir(learning_dir), exist_ok=True)
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write(build_weekly_markdown(learning_dir, today=today))
    except (OSError, TypeError) as e:
        logging.error("Report write failed in save_weekly: %s", e, exc_info=True)
        raise
    return p


def save_monthly(learning_dir, today=None):
    today = today or datetime.date.today()
    md, svg = build_monthly_markdown(learning_dir, today=today)
    try:
        os.makedirs(_rdir(learning_dir), exist_ok=True)
        md_p = os.path.join(_rdir(learning_dir),
                            "monthly_%04d-%02d.md" % (today.year, today.month))
        svg_p = os.path.join(_rdir(learning_dir),
                             "trend_%04d-%02d.svg" % (today.year, today.month))
        with open(md_p, "w", encoding="utf-8-sig") as f:
            f.write(md)
        with open(svg_p, "w", encoding="utf-8") as f:
            f.write(svg)
    except (OSError, TypeError) as e:
        logging.error("Report write failed in save_monthly: %s", e, exc_info=True)
        raise
    return md_p, svg_p


def ensure_reports(learning_dir, today=None):
    """启动钩子: 当周/当月报告缺才生成。返回 {created:[...], weekly, monthly}
    周报检查名必须与落盘名同用【周一锚定】——曾用今天日期当键,
    同一周内每次启动都误判缺失而重复生成(实机冒烟抓到后修复)。"""
    t = today or datetime.date.today()
    monday = t - datetime.timedelta(days=t.weekday())
    wname = "weekly_" + monday.strftime("%Y%m%d") + ".md"
    mname = "monthly_%04d-%02d.md" % (t.year, t.month)
    rdir = _rdir(learning_dir)
    existing = set(os.listdir(rdir)) if os.path.isdir(rdir) else set()
    created = []
    weekly = None
    if wname not in existing:
        weekly = save_weekly(learning_dir, today=t)
        created.append(os.path.basename(weekly))
    monthly = None
    if mname not in existing:
        monthly, _svg = save_monthly(learning_dir, today=t)
        created.append(os.path.basename(monthly))
    return {"created": created, "weekly": weekly, "monthly": monthly}


def list_reports(learning_dir):
    """reports 目录清单, 名字降序(周报月报名字都自带时间, 字典序即新→旧)"""
    rdir = _rdir(learning_dir)
    out = []
    if os.path.isdir(rdir):
        for fn in os.listdir(rdir):
            p = os.path.join(rdir, fn)
            if os.path.isfile(p):
                out.append({"name": fn, "mtime": int(os.path.getmtime(p))})
    out.sort(key=lambda x: x["name"], reverse=True)
    return out


_NAME_RE = re.compile(r"^[\w.-]+\.md$")


def read_report(learning_dir, name):
    """按名读报告正文; 只允许纯文件名(拒绝任何路径穿越), 不存在返回 None"""
    if not name or not _NAME_RE.match(os.path.basename(name)):
        return None
    p = os.path.join(_rdir(learning_dir), os.path.basename(name))
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8-sig") as f:
        return f.read()
