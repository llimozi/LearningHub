# -*- coding: utf-8 -*-
"""csrf_test.py —— 本地服务 CSRF 防护回归测试 (v1.10 · 纯标准库)

覆盖: _is_loopback_host 主机解析 / _check_origin_headers 头校验。
任何对 Handler CSRF 防护的改动都需保证此套件绿。
"""
from build_dashboard import Handler


# ---------------- _is_loopback_host ----------------
def test_is_loopback_host_accepts_127():
    assert Handler._is_loopback_host("127.0.0.1") is True
    assert Handler._is_loopback_host("127.0.0.1:8765") is True


def test_is_loopback_host_accepts_localhost():
    assert Handler._is_loopback_host("localhost") is True
    assert Handler._is_loopback_host("localhost:8765") is True


def test_is_loopback_host_accepts_ipv6_loopback():
    assert Handler._is_loopback_host("::1") is True
    assert Handler._is_loopback_host("[::1]:8765") is True


def test_is_loopback_host_rejects_external():
    assert Handler._is_loopback_host("evil.com") is False
    assert Handler._is_loopback_host("127.0.0.1.evil.com") is False       # 后缀攻击
    assert Handler._is_loopback_host("192.168.1.1") is False              # 内网≠本机
    assert Handler._is_loopback_host("10.0.0.1") is False


def test_is_loopback_host_rejects_empty_and_garbage():
    assert Handler._is_loopback_host("") is False
    assert Handler._is_loopback_host(None) is False


# ---------------- _check_origin_headers ----------------
def test_check_origin_allows_loopback_origin():
    h = {"Origin": "http://127.0.0.1:8765"}
    assert Handler._check_origin_headers(h) is True


def test_check_origin_allows_loopback_referer():
    h = {"Referer": "http://localhost:8765/dashboard"}
    assert Handler._check_origin_headers(h) is True


def test_check_origin_rejects_external_origin():
    h = {"Origin": "http://attacker.com"}
    assert Handler._check_origin_headers(h) is False
    h2 = {"Origin": "https://evil.com:443/anything"}
    assert Handler._check_origin_headers(h2) is False


def test_check_origin_rejects_file_scheme():
    """静态快照(file:// 打开)不能改数据; 浏览器无法伪造此头绕过。"""
    h = {"Origin": "file:///C:/path/to/dashboard.html"}
    assert Handler._check_origin_headers(h) is False


def test_check_origin_rejects_data_and_javascript():
    h = {"Origin": "data:text/html,<script>...</script>"}
    assert Handler._check_origin_headers(h) is False
    h2 = {"Origin": "javascript:fetch('/api/toggle',...)"}
    assert Handler._check_origin_headers(h2) is False


def test_check_origin_allows_no_headers_back_compat():
    """无 Origin/Referer 视为非浏览器(urllib/curl/本地脚本), 放行保向后兼容。"""
    assert Handler._check_origin_headers({}) is True
    assert Handler._check_origin_headers(None) is True
    h = {"User-Agent": "curl/7.0"}                          # 无 Origin/Referer
    assert Handler._check_origin_headers(h) is True


def test_check_origin_prefers_origin_over_referer():
    """Origin 优先: Origin 跨源但 Referer 同源, 仍判跨源(防 Referer 欺骗)。"""
    h = {"Origin": "http://attacker.com", "Referer": "http://127.0.0.1:8765/"}
    assert Handler._check_origin_headers(h) is False


def test_check_origin_uses_referer_when_no_origin():
    """无 Origin 头时, 用 Referer 兜底(部分浏览器/老客户端)。"""
    h = {"Referer": "http://127.0.0.1:8765/editor"}
    assert Handler._check_origin_headers(h) is True
    h2 = {"Referer": "http://attacker.com/"}
    assert Handler._check_origin_headers(h2) is False


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
