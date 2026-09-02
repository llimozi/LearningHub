# -*- coding: utf-8 -*-
"""reportio_test.py —— 周报/月报生成器单元测试 (v1.1 · 纯标准库)
跑法A: pytest reportio_test.py      跑法B: python reportio_test.py (零依赖runner)
覆盖: 周报四要素聚合(任务/新知识点/复习次数/建议)与窗口过滤 /
      空数据优雅降级 / 月报四周分桶与手绘SVG形状 / 文件命名(周一锚定+月份) /
      ensure 幂等不重复生成 / 列表排序与路径穿越拒收。全部临时目录+固定日期。
"""
import datetime
import json
import os
import shutil
import tempfile

import reportio
from forgetting import sync_from_analysis, mark_reviewed

TODAY = datetime.date(2099, 7, 13)          # 周一
NOWDT = datetime.datetime(2099, 7, 13, 8, 0)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _hist(entries):
    """entries: [(date_str, total, done)]"""
    return [{"date": d, "total": t, "done": n,
             "rate": round(n / t, 4) if t else 0.0} for d, t, n in entries]


def _dir_with_history(entries, notes=None):
    d = tempfile.mkdtemp()
    _write(os.path.join(d, "tasks.json"),
           {"version": 3, "days": {}, "history": _hist(entries),
            "fatigue": {"active": False}, "log": []})
    if notes:
        _write(os.path.join(d, "daily", "analysis.json"), {"notes": notes})
        sync_from_analysis(d, today=TODAY)
    return d


# ---------------- 周报 ----------------
def test_weekly_contains_core_sections_and_counts():
    # 窗口内(7-07~7-13)完成 2+1+1=4 条; 窗口外(7-01)不计
    d = _dir_with_history([
        ("2099-07-01", 3, 3),                       # 窗口外
        ("2099-07-07", 2, 2),
        ("2099-07-09", 2, 1),
        ("2099-07-12", 1, 1),
    ], notes={"2099-07-10": {"topic": "A", "concepts": ["新概念"],
                             "tags": [], "code_langs": []}})
    try:
        mark_reviewed(d, "新概念", quality=4, now=datetime.datetime(2099, 7, 11, 9, 0))
        mark_reviewed(d, "新概念", quality=4, now=datetime.datetime(2099, 7, 12, 9, 0))
        md = reportio.build_weekly_markdown(d, today=TODAY)
        assert "# 学习周报 · 2099-07-07 ~ 2099-07-13" in md, md[:80]
        assert "本周完成 **4**" in md, md                    # 只统计窗口内
        assert "达标天数 **2** 天" in md                     # rate>=0.8 的两天(07-07,07-12)
        assert "新概念" in md and "新增知识点 **1** 个" in md
        assert "本周复习 **2** 次" in md
        assert "下周建议" in md                              # 规则引擎段落必在(空也有占位)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_weekly_new_concepts_excludes_old_first_seen():
    d = _dir_with_history([], notes={
        "2099-06-01": {"topic": "老", "concepts": ["旧知识"], "tags": [], "code_langs": []},
        "2099-07-09": {"topic": "新", "concepts": ["新知识"], "tags": [], "code_langs": []}})
    try:
        md = reportio.build_weekly_markdown(d, today=TODAY)
        assert "新知识" in md and "旧知识" not in md.split("## 二")[1].split("## 三")[0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_weekly_empty_data_degrades_gracefully():
    d = tempfile.mkdtemp()
    try:
        md = reportio.build_weekly_markdown(d, today=TODAY)
        assert "# 学习周报" in md
        assert "本周完成 **0**" in md
        assert "暂无" in md                                  # 各段都有零值占位而非崩溃
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_weekly_suggestions_come_from_recommender():
    # 构造「需复习」卡片: 概念 5 天前出现且只出现过一次 -> review 建议必出
    d = _dir_with_history([], notes={
        "2099-07-08": {"topic": "R", "concepts": ["待复习点"], "tags": [], "code_langs": []}})
    try:
        md = reportio.build_weekly_markdown(d, today=TODAY)
        seg = md.split("## 四")[1]
        assert "待复习点" in seg, md                          # 建议段引用了推荐引擎输出
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 月报与 SVG ----------------
def test_monthly_buckets_four_weeks_and_svg_shape():
    entries = []
    for back in (26, 20, 13, 6, 2):                         # 跨四窗的散点
        day = TODAY - datetime.timedelta(days=back)
        entries.append((day.isoformat(), 2, 1))
    d = _dir_with_history(entries)
    try:
        md, svg = reportio.build_monthly_markdown(d, today=TODAY)
        assert "# 学习月报 · 2099-07" in md, md[:60]
        assert "四周趋势" in md
        assert svg.lstrip().startswith("<svg") and svg.rstrip().endswith("</svg>")
        assert "<polyline" in svg
        assert svg.count("<circle") == 4                    # 四个数据点
        pts = svg.split('points="')[1].split('"')[0].split()
        assert len(pts) == 4, pts                           # 折线四个顶点
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_monthly_values_match_history():
    # 第一个窗(最老) done=0, 最新窗 done=6 -> 折线值应递增到 6
    entries = [("2099-06-16", 3, 0),
               ("2099-07-10", 3, 3), ("2099-07-11", 3, 3)]
    d = _dir_with_history(entries)
    try:
        _, svg = reportio.build_monthly_markdown(d, today=TODAY)
        raw = svg.split('data-values="')[1].split('"')[0]   # 空格分隔的原始值序列
        vals = [int(v) for v in raw.split()]
        assert len(vals) == 4 and vals[0] == 0 and vals[-1] == 6, vals
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_save_weekly_anchor_to_monday_of_week():
    d = tempfile.mkdtemp()
    try:
        # 不变量: 同一周的任意两天必须落到同一份周报档名(周一锚定)
        p1 = reportio.save_weekly(d, today=datetime.date(2099, 7, 15))   # 周二
        p2 = reportio.save_weekly(d, today=datetime.date(2099, 7, 19))   # 周六
        n1 = os.path.basename(p1)
        assert n1 == os.path.basename(p2), (n1, os.path.basename(p2))
        expected_monday = datetime.date(2099, 7, 15) - datetime.timedelta(
            days=datetime.date(2099, 7, 15).weekday())
        assert n1 == "weekly_" + expected_monday.strftime("%Y%m%d") + ".md", n1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_save_monthly_creates_md_and_svg_pair():
    d = tempfile.mkdtemp()
    try:
        md_p, svg_p = reportio.save_monthly(d, today=TODAY)
        assert os.path.basename(md_p) == "monthly_2099-07.md"
        assert os.path.basename(svg_p) == "trend_2099-07.svg"
        assert os.path.exists(md_p) and os.path.exists(svg_p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ensure_reports_idempotent_no_duplicate_generation():
    d = tempfile.mkdtemp()
    try:
        r1 = reportio.ensure_reports(d, today=TODAY)
        r2 = reportio.ensure_reports(d, today=TODAY)
        rdir = os.path.join(d, "reports")
        files1 = sorted(os.listdir(rdir))
        files2 = sorted(os.listdir(rdir))
        assert files1 == files2 and len(files1) == 3, files1   # 周1 + 月1 + svg1, 二跑零新增
        assert r1["created"] != r2["created"]                  # 第二轮应报告没有新建
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ensure_same_week_different_days_generates_once():
    """周一锚定回归锁: 曾用今天日期当检查键, 同周内每次启动都重复生成(实机抓到)"""
    d = tempfile.mkdtemp()
    try:
        r1 = reportio.ensure_reports(d, today=datetime.date(2099, 7, 15))   # 周二
        assert len(r1["created"]) == 2, r1                                  # 周+月首建
        r2 = reportio.ensure_reports(d, today=datetime.date(2099, 7, 19))   # 同周周六
        weeklies = [f for f in os.listdir(os.path.join(d, "reports"))
                    if f.startswith("weekly_")]
        assert len(weeklies) == 1 and r2["created"] == [], (weeklies, r2)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 列表与读取 ----------------
def test_list_reports_sorted_desc_and_read_roundtrip():
    d = tempfile.mkdtemp()
    try:
        reportio.save_weekly(d, today=datetime.date(2099, 7, 13))
        reportio.save_weekly(d, today=datetime.date(2099, 7, 6))   # 上一周
        lst = reportio.list_reports(d)
        assert len(lst) == 2 and lst[0]["name"].startswith("weekly_")
        # 内容不同 -> mtime 相同也可能并列; 用名字降序兜底校验
        names = [x["name"] for x in lst]
        assert names == sorted(names, reverse=True)
        body = reportio.read_report(d, names[0])
        assert body and body.startswith("# 学习周报")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_read_report_refuses_path_traversal():
    d = tempfile.mkdtemp()
    try:
        assert reportio.read_report(d, "..\\tasks.json") is None
        assert reportio.read_report(d, "../../tasks.json") is None
        assert reportio.read_report(d, "不存在.md") is None
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
