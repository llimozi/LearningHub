# -*- coding: utf-8 -*-
"""route_contract_test.py —— D-6-0 路由 HTTP 行为契约测试。

定位: 补充 routing_test.py(结构性契约)之外的 HTTP 行为契约。
覆盖: 404 / 方法错配(无 405, 既有语义) / 501(unsupported method) /
413(body limit 前置) / CSRF(Origin 优先 + Referer fallback + 无头放行) /
malformed JSON(既有降级行为) / 业务 error schema / 静态资源 / 表完整性。

数据隔离: 复用 routing_test._HTTPServer(patch BASE/TASKS_FILE + save 打桩),
绝不触碰真实数据文件。413 用原始 socket 只发请求头(服务端读头即拒绝,
证明拦截发生在 body 读取 / dispatch / handler 之前)。

本文件只锁定行为, 不修改任何生产代码。
"""
import json
import os
import socket
import sys
import http.client
import urllib.error
import urllib.request

import _app.server as srv
import _app.services as services
from routing_test import _HTTPServer

Handler = srv.Handler


# ---------------- 统一 HTTP 请求辅助(返回 status, headers_dict, body) ----------------
def _http(port, method, path, body=None, origin=None, referer=None, raw_body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Content-Type": "application/json"}
    if origin:
        hdrs["Origin"] = origin
    if referer:
        hdrs["Referer"] = referer
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    try:
        conn.request(method, path, body=data, headers=hdrs)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    except Exception as e:
        return "EXC", {}, str(e).encode("utf-8")
    finally:
        conn.close()


def _raw_status_line(port, method, path, content_length):
    """原始 socket: 只发请求头(带超大 Content-Length), 服务端读完头即响应。
    用于证明 body limit 在读取 body 之前拦截, 且不发 body 不卡死。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    req = ("%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
           "Content-Length: %d\r\n\r\n" % (method, path, content_length)).encode()
    s.sendall(req)
    s.settimeout(5)
    resp = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\r\n\r\n" in resp:
                break
    except socket.timeout:
        pass
    finally:
        s.close()
    line = resp.split(b"\r\n", 1)[0].decode("latin1", "replace")
    return line


def _json(body):
    return json.loads(body.decode("utf-8"))


# ---------------- 1. 正常 GET ----------------
def _seed_static_assets(s):
    """隔离 BASE 下补齐 templates/dashboard.js + dashboard.css 副本并重置进程级缓存。
    _read_dashboard_js/_read_dashboard_css 有进程级缓存: 隔离 BASE 首次读取失败会缓存空串,
    导致静态资源路由误判为空。seed 使路由走真实文件读取路径。"""
    import shutil
    import _app.data as app_data
    root = os.path.dirname(os.path.abspath(__file__))
    dst_dir = os.path.join(s._tmp, "templates")
    os.makedirs(dst_dir, exist_ok=True)
    for fn in ("dashboard.js", "dashboard.css"):
        shutil.copy2(os.path.join(root, "templates", fn),
                     os.path.join(dst_dir, fn))
    prev_js = app_data._DASHBOARD_JS_CACHE
    prev_css = app_data._DASHBOARD_CSS_CACHE
    app_data._DASHBOARD_JS_CACHE = None      # 强制重新读取(读 seed 副本)
    app_data._DASHBOARD_CSS_CACHE = None
    return (prev_js, prev_css)


def test_get_html_root():
    """GET / -> 200 text/html(SPA fallback 主入口)。"""
    s = _HTTPServer()
    try:
        code, hdrs, body = _http(s.port, "GET", "/")
        assert code == 200, code
        assert "text/html" in hdrs.get("Content-Type", ""), hdrs
        low = body.lower()
        assert b"<html" in low or b"<!doctype" in low, "根路径应返回 HTML"
    finally:
        s.close()


def test_get_api_state():
    """GET /api/state -> 200 application/json, schema 含 days(任务库真源)。"""
    s = _HTTPServer()
    try:
        code, hdrs, body = _http(s.port, "GET", "/api/state")
        assert code == 200, code
        assert "application/json" in hdrs.get("Content-Type", ""), hdrs
        j = _json(body)
        assert isinstance(j, dict) and "days" in j, "state 应含 days"
    finally:
        s.close()


def test_get_json_theme_with_query():
    """GET /api/theme?name=dracula -> 200 JSON {ok, name, css}(query 参数路由)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "GET", "/api/theme?name=dracula")
        assert code == 200, code
        j = _json(body)
        assert j.get("ok") is True
        assert isinstance(j.get("css"), str) and j["css"], "css 应为非空字符串"
    finally:
        s.close()


def test_get_static_dashboard_js():
    """GET /dashboard.js -> 200 application/javascript + 非空(D-5a 静态资源)。"""
    s = _HTTPServer()
    prev_js, prev_css = _seed_static_assets(s)
    try:
        code, hdrs, body = _http(s.port, "GET", "/dashboard.js")
        assert code == 200, code
        assert "javascript" in hdrs.get("Content-Type", ""), hdrs
        assert len(body) > 1000, "dashboard.js 不应为空(len=%d)" % len(body)
    finally:
        import _app.data as app_data
        app_data._DASHBOARD_JS_CACHE = prev_js
        app_data._DASHBOARD_CSS_CACHE = prev_css
        s.close()


def test_get_static_dashboard_css():
    """GET /dashboard.css -> 200 text/css + 非空(D-8-1 静态资源)。"""
    s = _HTTPServer()
    prev_js, prev_css = _seed_static_assets(s)
    try:
        code, hdrs, body = _http(s.port, "GET", "/dashboard.css")
        assert code == 200, code
        assert "text/css" in hdrs.get("Content-Type", ""), hdrs
        assert len(body) > 1000, "dashboard.css 不应为空(len=%d)" % len(body)
    finally:
        import _app.data as app_data
        app_data._DASHBOARD_JS_CACHE = prev_js
        app_data._DASHBOARD_CSS_CACHE = prev_css
        s.close()


# ---------------- 2. POST 正常行为 ----------------
def test_post_simple_help():
    """POST /api/help -> 200 JSON {ok: true, markdown}(无参只读 POST)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/help", {})
        assert code == 200, code
        j = _json(body)
        assert j.get("ok") is True
        assert isinstance(j.get("markdown"), str), j
    finally:
        s.close()


def test_post_write_priority_schema():
    """POST /api/priority -> 200 JSON {ok, id, priority}(写路由, save 已打桩)。
    隔离环境无该任务 -> ok:false, 但 schema 结构必须完整。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/priority",
                                  {"id": "t1", "priority": 1})
        assert code == 200, code
        j = _json(body)
        assert isinstance(j.get("ok"), bool)
        assert j.get("id") == "t1"
        assert j.get("priority") == 1
    finally:
        s.close()


def test_post_mark_reviewed_ok_schema():
    """POST /api/mark_reviewed -> 200 JSON {ok: bool}(D-6-1 修复后回归)。
    D-6-0 时代该端点抛 TypeError 致连接中断(diagnose_mark_reviewed.py 复现);
    修复后必须 200 + 完整 schema。隔离环境概念不存在 -> ok:false, 结构仍完整。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/mark_reviewed",
                                  {"concept": "测试概念"},
                                  origin="http://127.0.0.1:8765")
        assert code == 200, "mark_reviewed 应 200(修复后), 实际 %s" % code
        j = _json(body)
        assert isinstance(j.get("ok"), bool), j
    finally:
        s.close()


# ---------------- 3. 404 Contract ----------------
def test_404_random_path():
    """POST 随机不存在路径 -> 404 JSON {"ok": false}(content-type 锁定)。"""
    s = _HTTPServer()
    try:
        code, hdrs, body = _http(s.port, "POST", "/this-route-does-not-exist", {})
        assert code == 404, code
        assert "application/json" in hdrs.get("Content-Type", ""), hdrs
        j = _json(body)
        assert j.get("ok") is False
    finally:
        s.close()


def test_404_post_to_get_only_route():
    """POST 打 GET-only 路由(/api/state) -> 404(既有语义, 无 405)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, _body = _http(s.port, "POST", "/api/state", {})
        assert code == 404, code
    finally:
        s.close()


# ---------------- 4. Method Mismatch(既有语义: GET 打 POST-only 落 HTML fallback) ----------------
def test_method_mismatch_get_on_post_route():
    """GET 打 POST-only 路由(/api/toggle) -> 200 HTML fallback(既有行为, 非 405)。"""
    s = _HTTPServer()
    try:
        code, hdrs, body = _http(s.port, "GET", "/api/toggle")
        assert code == 200, code
        low = body.lower()
        assert b"<html" in low or b"<!doctype" in low, "应返回 HTML 页面"
        assert "text/html" in hdrs.get("Content-Type", ""), hdrs
    finally:
        s.close()


# ---------------- 5. Unsupported Method(501) ----------------
def test_unsupported_method_501():
    """HEAD/OPTIONS/PUT 未实现 -> 501(BaseHTTPRequestHandler 默认)。"""
    s = _HTTPServer()
    try:
        for method in ("HEAD", "OPTIONS", "PUT"):
            code, _hdrs, _body = _http(s.port, method, "/api/state")
            assert code == 501, "%s -> %s" % (method, code)
    finally:
        s.close()


# ---------------- 6. 413 Body Limit(拦截发生在 dispatch/handler 之前) ----------------
def test_413_oversized_body_status():
    """11MB Content-Length -> 413; 原始 socket 只发头即被拒(未读 body)。"""
    s = _HTTPServer()
    try:
        line = _raw_status_line(s.port, "POST", "/api/help", 11 * 1024 * 1024)
        assert " 413 " in line, "期望 413, 实际: %r" % line
    finally:
        s.close()


def test_413_rejected_before_dispatch():
    """证明拦截在 dispatch/状态准备之前: patch _expire_fatigue_meta 为抛异常 stub,
    超大 body 请求不触发 stub(未执行到 L183); 小 body 请求触发(证明 stub 生效)。"""
    s = _HTTPServer()
    orig = services._expire_fatigue_meta

    def boom(st=None):
        raise AssertionError("413 场景不应执行到 _expire_fatigue_meta")
    try:
        services._expire_fatigue_meta = boom
        line = _raw_status_line(s.port, "POST", "/api/help", 11 * 1024 * 1024)
        assert " 413 " in line, line          # 大 body: 413, stub 未被调(若被调则 raise)
        # 小 body 对照组: 应执行到 L183 触发 stub 异常 -> 连接异常而非正常 200
        code, _h, _b = _http(s.port, "POST", "/api/help", {})
        assert code == "EXC", "小 body 应触发 stub 异常, 实际 %s" % code
    finally:
        services._expire_fatigue_meta = orig
        s.close()


def test_413_within_limit_ok():
    """<10MB body 正常进入 dispatch(对照组): 500KB -> 200。"""
    s = _HTTPServer()
    try:
        payload = json.dumps({"pad": "x" * (500 * 1024)})
        code, _hdrs, body = _http(s.port, "POST", "/api/help", raw_body=payload.encode())
        assert code == 200, code
        assert _json(body).get("ok") is True
    finally:
        s.close()


# ---------------- 7. CSRF Contract ----------------
def test_csrf_evil_origin_403():
    """外部 Origin -> 403 + csrf err。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/help", {}, origin="https://evil.example")
        assert code == 403, code
        j = _json(body)
        assert j.get("ok") is False
        assert "csrf" in str(j.get("err", "")).lower()
    finally:
        s.close()


def test_csrf_loopback_origin_ok():
    """loopback Origin(http://127.0.0.1:8765) -> 200 正常进入 handler。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/help", {},
                                  origin="http://127.0.0.1:8765")
        assert code == 200, code
        assert _json(body).get("ok") is True
    finally:
        s.close()


def test_csrf_no_origin_ok():
    """无 Origin/Referer(纯工具场景) -> 放行 200。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/help", {})
        assert code == 200, code
    finally:
        s.close()


def test_csrf_origin_priority_over_referer():
    """Origin 优先: Origin=evil + Referer=loopback -> 403(不因 loopback Referer 放行)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, _body = _http(s.port, "POST", "/api/help", {},
                                   origin="https://evil.example",
                                   referer="http://127.0.0.1:8765/")
        assert code == 403, code
    finally:
        s.close()


def test_csrf_referer_fallback_evil():
    """无 Origin + Referer=evil -> 403(Referer fallback 生效)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, _body = _http(s.port, "POST", "/api/help", {},
                                   referer="https://evil.example/")
        assert code == 403, code
    finally:
        s.close()


def test_csrf_referer_fallback_loopback():
    """无 Origin + Referer=loopback -> 200(Referer fallback 放行)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, _body = _http(s.port, "POST", "/api/help", {},
                                   referer="http://127.0.0.1:8765/")
        assert code == 200, code
    finally:
        s.close()


# ---------------- 8. Malformed JSON Contract(既有降级行为) ----------------
def test_malformed_json_degrades_to_empty():
    """非法 JSON -> 不 400, 降级 req={} 继续执行(锁定既有行为防重构误改)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/help", raw_body=b"{bad json")
        assert code == 200, "既有行为: malformed JSON 应降级执行而非 400, 实际 %s" % code
        j = _json(body)
        assert j.get("ok") is True, "降级 req={} 后 /api/help 仍应正常响应"
    finally:
        s.close()


# ---------------- 9. 业务 Error Schema(200 + {"ok": false, "err": ...}) ----------------
def test_business_err_schema_save_note_bad_date():
    """POST /api/save_note 日期非法(不匹配 YYYY-MM-DD) -> 200 {"ok": false, "err": str}。
    注: "2026-13-99" 能通过 \\d{2} 正则(既有宽松校验), 须用真不匹配输入触发 err 分支。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/save_note",
                                  {"date": "bad", "content": "x"})
        assert code == 200, code
        j = _json(body)
        assert j.get("ok") is False
        assert isinstance(j.get("err"), str) and j["err"]
    finally:
        s.close()


def test_business_err_schema_analyze_bad_date():
    """POST /api/analyze 日期非法 -> 200 {"ok": false, "err": str}。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "POST", "/api/analyze",
                                  {"date": "bad"})
        assert code == 200, code
        j = _json(body)
        assert j.get("ok") is False
        assert isinstance(j.get("err"), str) and j["err"]
    finally:
        s.close()


def test_business_err_schema_load_note_bad_date():
    """GET /api/load_note 日期非法(不匹配正则) -> 200 {"exists": false, "err": str}。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "GET", "/api/load_note?date=bad")
        assert code == 200, code
        j = _json(body)
        assert j.get("exists") is False
        assert isinstance(j.get("err"), str) and j["err"]
    finally:
        s.close()


def test_business_err_schema_report_bad_name():
    """GET /api/report 名字非法 -> 200 {"ok": false, "err": str}(reportio 路径校验)。"""
    s = _HTTPServer()
    try:
        code, _hdrs, body = _http(s.port, "GET", "/api/report?name=../etc/passwd")
        assert code == 200, code
        j = _json(body)
        assert j.get("ok") is False
        assert isinstance(j.get("err"), str) and j["err"]
    finally:
        s.close()


# ---------------- 10. Route Table Integrity(补充结构性契约) ----------------
def test_route_tables_no_cross_method_shadowing():
    """同一路径在 GET/POST 双表(如 /api/settings、/api/fatigue)互不覆盖:
    各自路由到本表 handler。"""
    s = _HTTPServer()
    try:
        for path, getter, postter in (("/api/settings", "_get_settings", "_post_settings"),
                                      ("/api/fatigue", "_get_fatigue", "_post_fatigue")):
            assert Handler._route_handler(path, Handler.GET_ROUTES) == getter
            assert Handler._route_handler(path, Handler.POST_ROUTES) == postter
        # 双表均存在的路径集合
        get_paths = {p for p, _ in Handler.GET_ROUTES}
        post_paths = {p for p, _ in Handler.POST_ROUTES}
        both = get_paths & post_paths
        assert both, "预期存在双表共享路径(settings/fatigue)"
        # 每个共享路径: GET 打 GET handler / POST 打 POST handler, 不串表
        code, _h, body = _http(s.port, "GET", "/api/settings")
        assert code == 200, code
        code, _h, body = _http(s.port, "POST", "/api/fatigue", {"on": True})
        assert code == 200, "POST /api/fatigue 应命中 POST 表, 实际 %s" % code
    finally:
        s.close()


def test_prefix_route_generic_no_mismatch():
    """泛化防前缀误匹配: /api/foo 不得命中 /api/foobar。"""
    for prefix in ("/api/state", "/api/settings", "/api/report", "/api/search"):
        lookalike = prefix + "ful"          # 如 /api/stateful
        assert Handler._route_handler(lookalike, Handler.GET_ROUTES) is None, lookalike
    assert Handler._route_handler("/api/reports/list", Handler.GET_ROUTES) == "_get_reports_list"
    assert Handler._route_handler("/api/report", Handler.GET_ROUTES) == "_get_report"


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
            print("FAIL", name, "->", repr(e)[:300])
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed
          else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
