# -*- coding: utf-8 -*-
"""review_feedback_test.py —— Phase C-D 复习完成反馈闭环聚焦测试
跑法A: pytest review_feedback_test.py   跑法B: python review_feedback_test.py (零依赖runner)
覆盖(Phase C-D 规格):
  1 toggle False->True 标记复习 / 2 重复 True 只标记一次 / 3 True->False 不标记 /
  4 batch done 标记新完成复习任务 / 5 batch 不重标记已完成 /
  6 普通任务不受影响 / 7 缺复习元数据安全 / 8 mark_reviewed 失败不打断完成 /
  9 重开后再完成仅对新转换标记一次
全部测试打桩 save_tasks/log_op/mark_reviewed/invalidate_cache, 绝不写真实数据。
"""
import contextlib

from _app import config, services
from _app.server import Handler


def _rtask(tid, concept="切片", done=False):
    return {"id": tid, "text": "复习：Python list 切片", "done": done,
            "carried": False, "src_date": config.TODAY, "priority": 1,
            "review_concept": concept, "review_source_date": "2099-07-08"}


def _ntask(tid, done=False):
    return {"id": tid, "text": "普通任务", "done": done,
            "carried": False, "src_date": config.TODAY, "priority": 2}


@contextlib.contextmanager
def _env(calls, fail=False):
    """打桩磁盘副作用: save_tasks/log_op/invalidate_cache 空操作,
    mark_reviewed 记 concept 到 calls(可注入 fail 抛异常)。"""
    import _app.data as app_data
    import _app.api as app_api
    import forgetting
    import analytics
    o1, o2 = app_data.save_tasks, app_api.log_op
    o3, o4 = forgetting.mark_reviewed, analytics.invalidate_cache

    def _mk(learning_dir, concept):
        calls.append(concept)
        if fail:
            raise IOError("模拟磁盘故障")
        return True

    app_data.save_tasks = lambda st: None
    app_api.log_op = lambda op: None
    forgetting.mark_reviewed = _mk
    analytics.invalidate_cache = lambda ld: None
    try:
        yield
    finally:
        app_data.save_tasks, app_api.log_op = o1, o2
        forgetting.mark_reviewed, analytics.invalidate_cache = o3, o4


class _FH:
    """伪 Handler: 只实现 _json(记录响应), 供 _post_batch 直调。"""

    def __init__(self):
        self.resp = None

    def _json(self, body):
        self.resp = body


# ---------- 1. toggle 单条: False->True 转换 -> 标记复习 ----------
def test_1_toggle_transition_marks():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1")]}}
        ok, dn, _ = services.toggle(st, "r1", True)
        assert ok and dn == 1, st
        assert calls == ["切片"], calls
        assert st["days"][config.TODAY][0]["done"] is True
        assert st["days"][config.TODAY][0].get("done_at"), "应补 done_at"


# ---------- 2. 重复 True 提交: 只标记一次 ----------
def test_2_repeat_true_marks_once():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1")]}}
        services.toggle(st, "r1", True)
        services.toggle(st, "r1", True)          # True->True 不触发
        assert calls == ["切片"], calls


# ---------- 3. True->False: 不标记 ----------
def test_3_true_to_false_no_mark():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1", done=True)]}}
        services.toggle(st, "r1", False)
        assert calls == [], calls
        t = st["days"][config.TODAY][0]
        assert t["done"] is False and "done_at" not in t, t


# ---------- 4. batch done: 标记新完成的复习任务 ----------
def test_4_batch_marks_newly_completed():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1"), _rtask("r2", concept="回测")]}}
        h = _FH()
        Handler._post_batch(h, {"action": "done", "ids": ["r1", "r2"],
                                "value": True}, st)
        assert h.resp and h.resp.get("ok") is True, h.resp
        assert sorted(calls) == ["切片", "回测"], calls


# ---------- 5. batch done: 不重标记已完成任务 ----------
def test_5_batch_no_remark_already_done():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1"), _rtask("r2", done=True)]}}
        h = _FH()
        Handler._post_batch(h, {"action": "done", "ids": ["r1", "r2"],
                                "value": True}, st)
        assert calls == ["切片"], calls          # r2 旧值 True -> 跳过


# ---------- 6. 普通任务(无 review_concept)完全不受影响 ----------
def test_6_normal_task_unaffected():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_ntask("n1")]}}
        services.toggle(st, "n1", True)
        assert calls == [], calls
        st2 = {"days": {config.TODAY: [_ntask("n2"), _ntask("n3")]}}
        h = _FH()
        Handler._post_batch(h, {"action": "done", "ids": ["n2", "n3"],
                                "value": True}, st2)
        assert calls == [], calls


# ---------- 7. 缺复习元数据: 安全 no-op ----------
def test_7_missing_meta_safe():
    calls = []
    with _env(calls):
        assert services.maybe_mark_reviewed({"id": "x"}) is False
        assert services.maybe_mark_reviewed({"id": "y", "review_concept": ""}) is False
        assert services.maybe_mark_reviewed({"id": "z", "review_concept": "  "}) is False
        assert calls == [], calls
        st = {"days": {config.TODAY: [{"id": "w1", "text": "t", "done": False}]}}
        ok, _, _ = services.toggle(st, "w1", True)
        assert ok and st["days"][config.TODAY][0]["done"] is True


# ---------- 8. mark_reviewed 失败: 不打断/不回滚任务完成 ----------
def test_8_mark_failure_does_not_break_completion():
    calls = []
    with _env(calls, fail=True):
        st = {"days": {config.TODAY: [_rtask("r1")]}}
        ok, dn, _ = services.toggle(st, "r1", True)
        assert ok, "完成不应被复习打卡拖垮"
        assert dn == 1 and st["days"][config.TODAY][0]["done"] is True
        st2 = {"days": {config.TODAY: [_rtask("r2")]}}
        h = _FH()
        Handler._post_batch(h, {"action": "done", "ids": ["r2"],
                                "value": True}, st2)
        assert h.resp and h.resp.get("ok") is True, h.resp
        assert st2["days"][config.TODAY][0]["done"] is True


# ---------- 9. 重开(True->False)后再完成: 仅对新转换标记一次 ----------
def test_9_reopen_then_complete_marks_new_transition():
    calls = []
    with _env(calls):
        st = {"days": {config.TODAY: [_rtask("r1")]}}
        services.toggle(st, "r1", True)          # 转换1 -> 标记
        services.toggle(st, "r1", False)         # 重开 -> 不标记
        services.toggle(st, "r1", True)          # 新转换 -> 再标记
        assert calls == ["切片", "切片"], calls


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
        except Exception as ex:
            failed += 1
            print("ERROR", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    import sys
    sys.exit(1 if failed else 0)
