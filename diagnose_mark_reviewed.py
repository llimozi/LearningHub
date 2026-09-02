# -*- coding: utf-8 -*-
"""diagnose_mark_reviewed.py —— D-6-0 mark_reviewed 已知 P1 Bug 复现诊断。

性质: 独立 diagnostic 工具(文件名不匹配 *_test.py, 不进 run_tests.py 主套件)。
目的: 稳定复现 _post_mark_reviewed 的 quality= 传参 TypeError,
      为 D-6-1 修复提供 BEFORE/AFTER 对照:
        BEFORE(当前): REPRODUCED=YES
        AFTER(修复):  REPRODUCED=NO(正常 200)

用法: python diagnose_mark_reviewed.py
"""
import io
import json
import os
import sys
import tempfile
import threading
import contextlib
import http.client
import inspect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import _app.config as app_config
import _app.data as app_data
import _app.server as srv
from http.server import ThreadingHTTPServer

Handler = srv.Handler

print("=" * 62)
print("diagnose_mark_reviewed — Known P1 Bug Reproduction")
print("=" * 62)

# ---- 证据 1: 源码层(静态) ----
src = inspect.getsource(Handler._post_mark_reviewed)
_json_sig = str(inspect.signature(Handler._json))
print("\n[1] 源码证据")
print("    _post_mark_reviewed 源码:")
for line in src.splitlines():
    print("      %s" % line)
print("    _json 签名: %s  <- 无 quality 参数" % _json_sig)
if "quality=" in src and "quality" not in _json_sig:
    print("    => 源码确认: quality= 关键字传给 _json() 将触发 TypeError")
else:
    print("    => 源码未发现该模式(bug 可能已修复)")

# ---- 证据 2: 运行时单元级(不依赖 HTTP) ----
class FakeSelf:
    """最小 self 替身: 仅提供 _json, 复现参数不匹配。"""
    def _json(self, obj, code=200):
        return ("_json_called", obj, code)

print("\n[2] 运行时证据(单元级)")
repro_unit = None
try:
    Handler._post_mark_reviewed(FakeSelf(), {"concept": "测试概念"}, None)
    print("    调用 _post_mark_reviewed: 未抛异常(bug 已修复)")
    repro_unit = False
except TypeError as e:
    print("    TypeError 复现: %s" % e)
    repro_unit = True

# ---- 证据 3: HTTP 级(完整链路, 客户端表现) ----
print("\n[3] 运行时证据(HTTP 级)")
_tmp = tempfile.mkdtemp()
_old_base, _old_tf = app_config.BASE, app_config.TASKS_FILE
_old_save = app_data.save_tasks
app_config.BASE = _tmp
app_config.TASKS_FILE = os.path.join(_tmp, "tasks.json")
app_data.save_tasks = lambda st: None

srv_obj = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv_obj.server_address[1]
threading.Thread(target=srv_obj.serve_forever, daemon=True).start()

conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
err_buf = io.StringIO()
try:
    with contextlib.redirect_stderr(err_buf):
        conn.request("POST", "/api/mark_reviewed",
                     body=json.dumps({"concept": "测试概念"}).encode(),
                     headers={"Content-Type": "application/json",
                              "Origin": "http://127.0.0.1:%d" % port})
        try:
            r = conn.getresponse()
            body = r.read()
            print("    HTTP 响应: %s %s" % (r.status, body[:80]))
            print("    => 正常响应(bug 已修复)")
            repro_http = False
        except Exception as e:
            print("    客户端异常: %s" % str(e)[:100])
            print("    => 连接中断/无状态码(bug 复现)")
            repro_http = True
finally:
    conn.close()
    srv_obj.shutdown()
    srv_obj.server_close()
    app_config.BASE, app_config.TASKS_FILE = _old_base, _old_tf
    app_data.save_tasks = _old_save

if err_buf.getvalue():
    tb_lines = [l for l in err_buf.getvalue().splitlines()
                if "TypeError" in l or "_json" in l or "quality" in l][:4]
    print("    服务端 traceback 关键行:")
    for l in tb_lines:
        print("      %s" % l.strip())

print("\n" + "=" * 62)
print("RESULT: REPRODUCED=%s (unit) / %s (http)" % ("YES" if repro_unit else "NO",
                                                    "YES" if repro_http else "NO"))
print("KNOWN P1 BUG: reproduced=YES fixed=NO" if (repro_unit or repro_http)
      else "KNOWN P1 BUG: reproduced=NO fixed=YES(需人工复核)")
print("=" * 62)
