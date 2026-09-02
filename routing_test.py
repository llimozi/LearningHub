# -*- coding: utf-8 -*-
"""routing_test.py —— v1.11 phase2.5b 路由重构(D-6) 回归测试。

验证对象: _app/server.py 的 dispatch 表(GET_ROUTES/POST_ROUTES)。
覆盖: 表与旧 if/elif 链的等价性(表序/重叠优先级)、匹配语义(防前缀误匹配)、
处理器齐全、HTTP 行为回归(端点 200 / CSRF 403 / 未知 404 / GET 未知落页面)。
数据隔离: patch _app.config.BASE/TASKS_FILE 到临时目录 + 打桩 data.save_tasks,
绝不触碰真实数据文件(教训: 数据文件与代码必须分离提交)。
"""
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import _app.config as app_config
import _app.data as app_data
import _app.server as srv

Handler = srv.Handler


def test_route_table_matches_legacy_order():
    """表序必须与原 if/elif 链一致(重叠路由的优先级靠表序)。
    关键重叠对: /api/reports/list 必须先于 /api/report 匹配。"""
    get_routes = [r for r, _ in Handler.GET_ROUTES]
    assert get_routes.index("/api/reports/list") < get_routes.index("/api/report")
    # 顺序稳定性: 首个路由必须是 /api/state(原 if/elif 链第一分支)
    assert Handler.GET_ROUTES[0][0] == "/api/state"
    # 基线端点覆盖: state/stateful 不存在前缀冲突
    assert "/api/state" in get_routes
    assert "/api/stateful" not in get_routes


def test_route_tables_well_formed():
    """无重复路由 + 每个处理器方法存在 + POST 处理器签名统一。"""
    for tbl in (Handler.GET_ROUTES, Handler.POST_ROUTES):
        routes = [r for r, _ in tbl]
        assert len(routes) == len(set(routes)), "路由重复!"
        for _, name in tbl:
            assert hasattr(Handler, name), "缺处理器 %s" % name
    for _, name in Handler.POST_ROUTES:
        sig = inspect.signature(getattr(Handler, name))
        assert list(sig.parameters) == ["self", "req", "st"], \
            "%s 签名异常: %s" % (name, sig)
    for _, name in Handler.GET_ROUTES:
        sig = inspect.signature(getattr(Handler, name))
        assert list(sig.parameters) == ["self"], \
            "%s 签名异常: %s" % (name, sig)


def test_match_route_semantics():
    """精确匹配/查询串/子路径/防前缀误匹配(与 _match_route 同语义)。"""
    m = Handler._match_route
    assert m("/api/state", "/api/state")
    assert m("/api/state?x=1", "/api/state")
    assert m("/api/state/child", "/api/state")
    assert not m("/api/stateful", "/api/state")        # 防误匹配核心用例
    assert not m("/api/sta", "/api/state")
    assert not m("/api/stateful?x=1", "/api/state")


def test_route_handler_lookup():
    """dispatch 查找: 命中/查询串/子路径/未知/重叠优先级。"""
    r = Handler._route_handler
    get = Handler.GET_ROUTES
    assert r("/api/state", get) == "_get_state"
    assert r("/api/state?x=1", get) == "_get_state"
    assert r("/api/state/child", get) == "_get_state"
    assert r("/api/stateful", get) is None            # 不误匹配
    assert r("/api/not_exist", get) is None
    # 重叠: /api/reports/list 命中列表而非 report
    assert r("/api/reports/list", get) == "_get_reports_list"
    assert r("/api/report?name=week1.md", get) == "_get_report"
    # 子路径守卫: /api/search 不命中 /api/settings
    assert r("/api/search?q=xx", get) == "_get_search"
    assert r("/api/settings", get) == "_get_settings"
    # POST 表
    post = Handler.POST_ROUTES
    assert r("/api/toggle", post) == "_post_toggle"
    assert r("/api/tasks/patch-done-at", post) == "_post_patch_done_at"
    assert r("/api/review/snooze-all", post) == "_post_snooze_all"
    assert r("/api/fatigue", post) == "_post_fatigue"


class _HTTPServer:
    """最小 HTTP 冒烟台: 真实服务 + 隔离 BASE/TASKS_FILE + save 打桩。"""

    def __init__(self):
        self._tmp = tempfile.mkdtemp()
        self._old_base = app_config.BASE
        self._old_tf = app_config.TASKS_FILE
        self._old_save = app_data.save_tasks
        app_config.BASE = self._tmp
        app_config.TASKS_FILE = os.path.join(self._tmp, "tasks.json")
        app_data.save_tasks = lambda st: None           # 打桩: 绝不写真实数据
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        app_config.BASE = self._old_base
        app_config.TASKS_FILE = self._old_tf
        app_data.save_tasks = self._old_save
        shutil.rmtree(self._tmp, ignore_errors=True)

    def get(self, path, origin=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path))
        if origin:
            req.add_header("Origin", origin)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()

    def post(self, path, body, origin=None):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        if origin:
            req.add_header("Origin", origin)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())


def test_http_get_endpoints():
    """GET 端点行为回归(隔离目录): 全部 200。"""
    s = _HTTPServer()
    try:
        for p in ["/api/state", "/api/stats", "/api/theme?name=dracula",
                  "/api/search?q=x", "/api/analytics", "/api/fatigue",
                  "/api/due_reviews", "/api/retention", "/api/help"]:
            code, _body = s.get(p)
            assert code == 200, "%s -> %s" % (p, code)
        # 未知 GET 落 HTML 页面(旧行为, 非 404)
        code, body = s.get("/api/stateful")
        assert code == 200
        low = body.lower()
        assert b"<html" in low or b"<!doctype" in low, "未知 GET 应返回页面"
    finally:
        s.close()


def test_http_post_csrf_and_404():
    """POST CSRF 防护 + 未知 404。"""
    s = _HTTPServer()
    try:
        code, j = s.post("/api/help", {}, origin="http://127.0.0.1:%d" % s.port)
        assert code == 200 and j.get("ok"), "loopback POST 应放行"
        try:
            s.post("/api/help", {}, origin="http://evil.com")
            raise AssertionError("evil origin 应 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403, "evil origin -> %s" % e.code
        try:
            s.post("/api/not_exist", {}, origin="http://127.0.0.1:%d" % s.port)
            raise AssertionError("未知 POST 应 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404, "未知 POST -> %s" % e.code
    finally:
        s.close()


def test_http_toggle_business_flow():
    """POST toggle 业务回归: 预置状态注入 + save 打桩, 验证 ok/计数。"""
    s = _HTTPServer()
    orig_load = app_data.load_tasks
    try:
        st = {"days": {app_config.TODAY: [
                {"id": "t1", "text": "x", "done": False,
                 "carried": False, "src_date": app_config.TODAY}]},
              "log": [], "meta": {}}
        app_data.load_tasks = lambda: st
        code, j = s.post("/api/toggle", {"id": "t1", "done": True},
                         origin="http://127.0.0.1:%d" % s.port)
        assert code == 200 and j.get("ok") is True, j
        assert j.get("today_total") == 1
        assert j.get("today_done") == 1
    finally:
        app_data.load_tasks = orig_load
        s.close()


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("PASS", name)
        except Exception as e:
            failed += 1
            print("FAIL", name, "->", repr(e)[:200])
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed
          else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
