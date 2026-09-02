# -*- coding: utf-8 -*-
"""firstrun_test.py —— 首次运行工作区初始化与八周路线图生成 单元测试 (v1.4)
跑法A: pytest firstrun_test.py      跑法B: python firstrun_test.py
覆盖: 缺什么建什么的默认结构 / 幂等二跑零新建 / 绝不覆盖用户已有数据 /
      路线图八周骨架与仪表盘解析兼容(阶段总览·当前复习队列标题) /
      周一锚定日期 / 已存在跳过与force重生成 / API层校验与串联。
全部临时目录+固定日期。
"""
import datetime
import json
import os
import shutil
import tempfile

import firstrun

TODAY = datetime.date(2099, 7, 13)               # 周一


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _jread(path):
    return json.loads(_read(path))


# ---------------- 工作区初始化 ----------------
def test_ensure_workspace_creates_missing_core():
    d = tempfile.mkdtemp()
    try:
        out = firstrun.ensure_workspace(d)
        assert set(out["created"]) >= {"tasks.json", "settings.json",
                                       "STATUS.json", "daily"}, out
        assert out["existed"] is False
        assert os.path.isdir(os.path.join(d, "daily"))
        st = _jread(os.path.join(d, "tasks.json"))
        assert st["version"] == 3 and st["days"] == {}           # 可解析的空任务库
        status = _jread(os.path.join(d, "STATUS.json"))
        assert "deadline" in status and "subjects" in status     # 总览骨架可渲染
        s = _jread(os.path.join(d, "settings.json"))
        assert s["theme"] == "dark"                              # 设置走统一默认模板
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ensure_workspace_idempotent_and_never_overwrites():
    d = tempfile.mkdtemp()
    try:
        firstrun.ensure_workspace(d)
        _write_custom = os.path.join(d, "tasks.json")
        import json as j
        with open(_write_custom, "w", encoding="utf-8") as f:
            j.dump({"version": 3, "days": {}, "history": [], "log": [],
                    "user_mark": "别动我"}, f)
        out2 = firstrun.ensure_workspace(d)
        assert out2["created"] == [] and out2["existed"] is True, out2
        assert _jread(_write_custom).get("user_mark") == "别动我"  # 已有不覆盖
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_partial_missing_only_creabs_gap():
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "daily"))
        out = firstrun.ensure_workspace(d)
        assert "daily" not in out["created"], out                 # 已存在的目录不算新建
        assert "STATUS.json" in out["created"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 路线图生成 ----------------
def test_roadmap_generates_eight_weeks_with_direction():
    d = tempfile.mkdtemp()
    try:
        p = firstrun.generate_roadmap("AI Agent 开发", d, today=TODAY)
        assert p and os.path.exists(p), p
        md = _read(p)
        assert "AI Agent 开发" in md, md[:80]
        assert "## 阶段总览" in md and "## 当前复习队列" in md    # 仪表盘 section 解析兼容
        weeks = [ln for ln in md.splitlines() if ln.startswith("| W")]
        assert len(weeks) == 8, weeks                             # 八周骨架整整齐齐
        for w in ("W0", "W7"):
            assert any(ln.startswith("| %s " % w) or ln.startswith("| %s" % w)
                       for ln in weeks), (w, weeks)
        assert "- [ ]" in md                                      # 复习队列带可勾选条目
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_roadmap_dates_anchor_to_given_monday():
    d = tempfile.mkdtemp()
    try:
        p = firstrun.generate_roadmap("X", d, today=TODAY)
        md = _read(p)
        assert TODAY.isoformat() in md                            # 第一周从锚定周一起算
        last = TODAY + datetime.timedelta(days=49)                # 第八周末尾=+49天
        assert last.isoformat() in md
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_roadmap_skipped_when_exists_unless_forced():
    d = tempfile.mkdtemp()
    try:
        rp = os.path.join(d, "ROADMAP.md")
        with open(rp, "w", encoding="utf-8") as f:
            f.write("# 用户自己的路线图")
        assert firstrun.generate_roadmap("Y", d, today=TODAY) is None, "已有必须跳过"
        assert "用户自己的路线图" in _read(rp)                     # 内容未被动过
        p2 = firstrun.generate_roadmap("Y", d, today=TODAY, force=True)
        assert p2 is not None and "用户自己的路线图" not in _read(p2)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- API 层 ----------------
def test_api_firstrun_requires_direction():
    from build_dashboard import api_firstrun
    d = tempfile.mkdtemp()
    try:
        r0 = api_firstrun("", learning_dir=d)
        assert r0["ok"] is False and "direction" in r0["err"], r0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_api_firstrun_wires_workspace_and_roadmap(tmpdir=None):
    from build_dashboard import api_firstrun
    d = tempfile.mkdtemp()
    try:
        r = api_firstrun("AI Agent 开发", learning_dir=d, today=TODAY)
        assert r["ok"] is True, r
        assert r["roadmap"] and os.path.exists(r["roadmap"])
        assert "tasks.json" in "".join(r["created"]) or r.get("existed") is True
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
