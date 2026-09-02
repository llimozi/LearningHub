# -*- coding: utf-8 -*-
"""server.py —— HTTP 服务层（原 build_dashboard.py Handler 类, Phase 2.5 迁移）。

v1.11 phase2.5b: 路由重构(D-6) — do_GET/do_POST 的 if/elif 链改为 dispatch 表
(GET_ROUTES/POST_ROUTES), 分支体抽取为 _get_*/_post_* 处理器方法, 行为逐字节等价。
匹配语义保持 _match_route 不变: 完全相等、后接 ?(查询串)、后接 /(子路径)。

依赖: api / services / data / config + 外部业务模块。
注意: 统一通过模块对象动态访问 config/data/services/api, 便于测试 patch 数据隔离。
render() 仍在 build_dashboard.py(Phase 2.6 迁移), 为避免循环 import 采用延迟导入。
"""
import json
import logging
import os
import re
import datetime
import urllib.parse
from http.server import BaseHTTPRequestHandler

import planner
import heatmap
import analyzer
import graph
import recommender
import analytics
import theme
import search
import nl_capture
import adaptive
import settings

from _app import api, config, data, services
from _app.utils import next_day


class Handler(BaseHTTPRequestHandler):
    # ---- v1.11 phase2.5b 路由表: (路由前缀, 处理器方法名) ----
    # 顺序即匹配优先级(与原 if/elif 链一致); 处理器统一签名:
    #   GET:  (self) -> 写响应; POST: (self, req, st) -> 写响应
    GET_ROUTES = [
        ("/api/state", "_get_state"),
        ("/api/stats", "_get_stats"),
        ("/api/tomorrow", "_get_tomorrow"),
        ("/api/heatmap", "_get_heatmap"),
        ("/api/review_cards", "_get_review_cards"),
        ("/api/graph", "_get_graph"),
        ("/api/analytics", "_get_analytics"),
        ("/api/fatigue", "_get_fatigue"),
        ("/api/suggest-slot", "_get_suggest_slot"),
        ("/api/weekly-report", "_get_weekly_report"),
        ("/api/daily-focus", "_get_daily_focus"),
        ("/api/recommendations", "_get_recommendations"),
        ("/api/settings", "_get_settings"),
        ("/api/mastery", "_get_mastery"),
        ("/api/theme", "_get_theme"),
        ("/api/search", "_get_search"),
        ("/api/due_reviews", "_get_due_reviews"),
        ("/api/retention", "_get_retention"),
        ("/api/reports/list", "_get_reports_list"),
        ("/api/report", "_get_report"),
        ("/api/export", "_get_export"),
        ("/api/notes", "_get_notes"),
        ("/api/load_note", "_get_load_note"),
        ("/dashboard.js", "_get_dashboard_js"),
        ("/dashboard.css", "_get_dashboard_css"),
        ("/editor", "_get_editor"),
    ]
    POST_ROUTES = [
        ("/api/toggle", "_post_toggle"),
        ("/api/rollover", "_post_rollover"),
        ("/api/priority", "_post_priority"),
        ("/api/save_note", "_post_save_note"),
        ("/api/weekly_report", "_post_weekly_report"),
        ("/api/analyze", "_post_analyze"),
        ("/api/settings", "_post_settings"),
        ("/api/tasks/patch-done-at", "_post_patch_done_at"),
        ("/api/review/snooze-all", "_post_snooze_all"),
        ("/api/fatigue", "_post_fatigue"),
        ("/api/mark_reviewed", "_post_mark_reviewed"),
        ("/api/backup", "_post_backup"),
        ("/api/import", "_post_import"),
        ("/api/reorder", "_post_reorder"),
        ("/api/batch", "_post_batch"),
        ("/api/quick-capture", "_post_quick_capture"),
        ("/api/undo", "_post_undo"),
        ("/api/firstrun", "_post_firstrun"),
        ("/api/help", "_post_help"),
    ]

    def log_message(self, *a):
        pass
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _match_route(path, route):
        """精确路由匹配: 防止 /api/state 误匹配 /api/stateful。
        匹配条件: 完全相等、或后接 ?(查询字符串)、或后接 /(子路径)。"""
        return path == route or path.startswith(route + "?") or path.startswith(route + "/")

    @classmethod
    def _route_handler(cls, path, routes):
        """dispatch 查找: 返回命中的处理器方法名; 无命中返回 None(表序=原 if/elif 序)。"""
        for route, name in routes:
            if path == route or path.startswith(route + "?") or path.startswith(route + "/"):
                return name
        return None

    # ---- v1.10 本地服务 CSRF 防护: 仅放行 loopback 来源 ----
    # 攻击面: 任意公网页面可对 127.0.0.1:8765 发 fetch(同源/部分浏览器绕过 CORS),
    # 改任务/导入恶意包/切疲劳模式。校验 Origin/Referer 的 host 必须在 loopback 白名单。
    _LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

    @classmethod
    def _is_loopback_host(cls, host):
        if not host:
            return False
        h = host.strip().lower()
        # IPv6 带方括号: [::1] 或 [::1]:8765
        if h.startswith("["):
            end = h.find("]")
            if end == -1:
                return False
            h = h[1:end]                            # 纯 IPv6 部分
        # IPv6 整体(无方括号): 含 ≥ 2 个冒号, 整体匹配 loopback
        if h.count(":") >= 2:
            return h in cls._LOOPBACK_HOSTS
        # IPv4:port 或 hostname:port: 剥端口再匹配
        if ":" in h:
            h = h.rsplit(":", 1)[0]
        return h in cls._LOOPBACK_HOSTS

    @classmethod
    def _check_origin_headers(cls, headers):
        """从 headers 字典(.get("Origin")/.get("Referer") 协议)读取来源并校验。
        纯函数化以便单测; 无头视为非浏览器放行, file:// 一律拒。"""
        origin = (headers.get("Origin") if headers else "") or ""
        referer = (headers.get("Referer") if headers else "") or ""
        src = origin or referer
        if not src:
            return True
        try:
            u = urllib.parse.urlparse(src)
            if u.scheme in ("http", "https"):
                return cls._is_loopback_host(u.hostname)
            return False                          # file:/data:/javascript: 一律拒
        except Exception:
            return False

    def _check_csrf(self):
        """POST 写操作必须同源: 包装 _check_origin_headers, 接 BaseHTTPRequestHandler.headers。"""
        return self._check_origin_headers(self.headers)

    # ================= do_GET / do_POST 薄分发 =================
    def do_GET(self):
        name = self._route_handler(self.path, self.GET_ROUTES)
        if name is None:
            import build_dashboard                 # Phase 2.6 迁移 render 后改直连
            html = build_dashboard.render(True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store, must-revalidate")   # v1.9修复: 页面实时渲染, 禁止浏览器缓存旧版
            self.end_headers()
            self.wfile.write(html)
            return
        getattr(self, name)()

    def do_POST(self):
        if not self._check_csrf():
            self._json({"ok": False, "err": "csrf: cross-origin request rejected"}, 403)
            return
        ln = int(self.headers.get("Content-Length", 0) or 0)
        if ln > config._MAX_POST_BYTES:             # 体积上限: 防恶意/大文件 OOM
            self._json({"ok": False, "err": "payload too large"}, 413)
            return
        body = self.rfile.read(ln) if ln else b"{}"
        try:
            req = json.loads(body.decode("utf-8"))
        except Exception:
            req = {}
        st = services._expire_fatigue_meta(data.load_tasks())
        name = self._route_handler(self.path, self.POST_ROUTES)
        if name is None:
            self._json({"ok": False}, 404)
            return
        getattr(self, name)(req, st)

    # ================= GET 处理器 =================
    def _get_state(self):
        self._json(data.load_tasks())

    def _get_stats(self):
        self._json(planner.get_stats(data.load_tasks()))

    def _get_tomorrow(self):
        st2 = data.load_tasks()
        planner.normalize_priorities(st2)
        self._json(planner.predict_tomorrow(st2))

    def _get_heatmap(self):
        self._json(heatmap.heatmap_payload(config.BASE, data.load_tasks()))

    def _get_review_cards(self):
        self._json({"cards": analyzer.get_review_cards(config.BASE)})

    def _get_graph(self):
        self._json(graph.build_graph(config.BASE))

    def _get_analytics(self):
        self._json(api.api_analytics())

    def _get_fatigue(self):
        self._json(api.api_fatigue_state())

    def _get_suggest_slot(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        pri_s = (q.get("priority") or ["2"])[0]
        pri = int(pri_s[1]) if pri_s[:1].upper() == "P" and pri_s[1:].isdigit() else (int(pri_s) if pri_s.isdigit() else 2)
        em = (q.get("est_minutes") or [None])[0]
        self._json({"ok": True, "slot": analytics.suggest_slot(
            data.load_tasks(), priority=pri,
            tag=(q.get("tag") or [None])[0],
            est_minutes=(int(em) if em and em.isdigit() else None))})

    def _get_weekly_report(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        wk = (q.get("week") or ["current"])[0]
        try:
            self._json({"ok": True, "report": analytics.generate_weekly_narrative(config.BASE, week=wk)})
        except Exception as e2:
            logging.error("Boundary error in do_GET.weekly-report: %s", e2,
                          exc_info=True)
            self._json({"ok": False, "err": str(e2)[:120]})

    def _get_daily_focus(self):
        self._json(api.api_daily_focus())

    def _get_recommendations(self):
        self._json(recommender.get_recommendations(config.BASE))

    def _get_settings(self):
        self._json(api.api_get_settings())

    def _get_mastery(self):
        self._json(api.api_mastery())

    def _get_theme(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self._json(api.api_theme((q.get("name") or [""])[0]))

    def _get_search(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self._json(api.api_search((q.get("q") or [""])[0],
                                  limit=int((q.get("limit") or ["20"])[0])))

    def _get_due_reviews(self):
        self._json(api.api_due_reviews())

    def _get_retention(self):
        self._json(api.api_retention())

    def _get_reports_list(self):
        self._json(api.api_list_reports())

    def _get_report(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self._json(api.api_read_report((q.get("name") or [""])[0]))

    def _get_export(self):
        payload = api.api_export()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        fname = "learninghub_export_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_notes(self):
        st3 = data.load_tasks()
        planner.normalize_priorities(st3)
        notes = heatmap.scan_daily(config.BASE)
        lst = []
        for dstr in sorted(notes.keys(), reverse=True):
            rec = {k2: v2 for k2, v2 in notes[dstr].items() if not k2.startswith("_")}
            rec["date"] = dstr
            rec["tasks"] = len(st3.get("days", {}).get(dstr, []))
            lst.append(rec)
        self._json({"notes": lst})

    def _get_load_note(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        ds = (q.get("date") or [""])[0]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ds or ""):
            self._json({"exists": False, "err": "日期格式须为 YYYY-MM-DD"})
            return
        p2 = os.path.join(config.BASE, "daily", ds + ".md")
        exists = os.path.exists(p2)
        content = ""
        if exists:
            with open(p2, encoding="utf-8") as f3:
                content = f3.read()
        self._json({"date": ds, "exists": exists, "content": content,
                    "words": len(re.sub(r"\s", "", content))})

    def _get_dashboard_js(self):
        """D-5a: 提供外链 dashboard.js 静态资源。"""
        js = data._read_dashboard_js()
        body = js.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _get_dashboard_css(self):
        """D-8-1: 提供外链 dashboard.css 静态资源(镜像 _get_dashboard_js)。"""
        css = data._read_dashboard_css()
        body = css.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _get_editor(self):
        ed_path = data.asset_path("editor.html")             # v1.4: 只读资源走双路径解析
        if os.path.exists(ed_path):
            with open(ed_path, encoding="utf-8") as f4:
                ed_html = f4.read()
        else:
            ed_html = "<h2>editor.html 缺失</h2>"
        # v1.3 主题: 编辑器与仪表盘共用变量根, 注入末位覆盖层
        try:
            ed_css = theme.override_css(theme.current_theme(config.BASE), target="editor")
            ed_html = ed_html.replace("<style>", "<style>" + ed_css, 1)
        except Exception:
            pass                                            # 主题注入失败不挡编辑器
        body_bytes = ed_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store, must-revalidate")   # 编辑器同样禁缓存
        self.end_headers()
        self.wfile.write(body_bytes)

    # ================= POST 处理器 =================
    def _post_toggle(self, req, st):
        ok, dn, tn = services.toggle(st, str(req.get("id", "")), req.get("done"))
        self._json({"ok": ok, "today_done": dn, "today_total": tn})

    def _post_rollover(self, req, st):
        desc = services.rollover(st, config.TODAY)
        info = planner.finalize_day(st, config.TODAY)
        # Phase B: 明日预算闭环 —— finalize_day 预测 × 自适应系数 → compose_tomorrow 落桶。
        # 组合只发生在本用户显式路径; 渲染(GET /) / auto_catchup / rollover 本体 / GET /api/tomorrow
        # 均不调用 compose_tomorrow(compose_test.py 的 J 组有源码级断言锁定)。
        cfg_ad = settings.load_settings(config.BASE).get("adaptive", {})
        ad = adaptive.evaluate(adaptive.recent_rates(st), cfg_ad)
        # Phase E-B: 多信号合成 —— 完成率为主, 叠加顺延率/疲劳/复习积压(E-A §9 护栏版)
        fused = adaptive.compose_factor(
            ad["factor"],
            carry_over=adaptive.carry_over_rate(st),
            fatigue=bool(info.get("fatigue", {}).get("active")),
            review_ratio=adaptive.review_completion_ratio(config.BASE),
            cfg=cfg_ad)
        budget = adaptive.apply_factor(info["tomorrow"]["predicted"], fused)
        nd = next_day(config.TODAY)
        # Phase C-B: 传 learning_dir+today 启用复习源(到期知识点 -> 明日任务)。
        comp = services.compose_tomorrow(st, nd, budget,
                                         cfg={"learning_dir": config.BASE,
                                              "today": config.TODAY})
        # Phase E-B: 计划 vs 实际诊断入 history(可回测), 旧记录兼容
        services.persist_compose_diagnostic(st, comp)
        data.save_tasks(st)
        for g in comp.get("generated", []):
            api.log_op({"id": "op-c-" + g["id"],
                        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                        "type": "quick_create",               # 复用既有撤销格式: 按 id 从桶移除
                        "label": "规划生成(" + g["line"] + "): " + g["text"][:20],
                        "undone": False,
                        "undo": {"task_id": g["id"], "date": nd}})
        self._json({"ok": True, "desc": desc, "fatigue": info["fatigue"],
                    "stats": info["stats"], "tomorrow": info["tomorrow"],
                    "composed": {"requested_budget": comp.get("requested_budget"),
                                 "existing_count": comp.get("existing_count"),
                                 "generated_count": comp.get("generated_count"),
                                 "review_generated": comp.get("review_generated"),
                                 "factor_base": ad["factor"],
                                 "factor": fused,
                                 "final_count": comp.get("final_count")}})

    def _post_priority(self, req, st):
        pid = str(req.get("id", ""))
        try:
            pri = max(1, min(3, int(req.get("priority", 2))))
        except Exception:
            pri = 2
        hit = False
        for t in st.get("days", {}).get(config.TODAY, []):
            if t.get("id") == pid:
                t["priority"] = pri
                hit = True
                break
        if hit:
            data.save_tasks(st)
        self._json({"ok": hit, "id": pid, "priority": pri})

    def _post_save_note(self, req, st):
        ds = str(req.get("date", ""))
        content = str(req.get("content", ""))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ds):
            self._json({"ok": False, "err": "日期格式须为 YYYY-MM-DD"})
            return
        p3 = os.path.join(config.BASE, "daily", ds + ".md")
        words = len(re.sub(r"\s", "", content))
        with open(p3, "w", encoding="utf-8-sig") as f5:
            f5.write(content)
        st4 = data.load_tasks()   # 知识资产事件入账(log 追加, 不改结构)
        st4.setdefault("log", []).append({"date": config.TODAY, "event": "note_created",
                                          "file": "daily/" + ds + ".md", "words": words,
                                          "tags": req.get("tags", "")})
        data.save_tasks(st4)
        try:                                            # v1.3: 保存即增量更新搜索索引
            search.update_note(config.BASE, ds)
        except Exception:
            pass                                        # 索引失败不阻塞保存主流程
        self._json({"ok": True, "path": "daily/" + ds + ".md", "words": words})

    def _post_weekly_report(self, req, st):
        self._json(services.weekly_report(data.load_tasks(), config.BASE))

    def _post_analyze(self, req, st):
        ds = str(req.get("date", "")) or None
        dates = [ds] if ds else None
        if ds and not re.match(r"^\d{4}-\d{2}-\d{2}$", ds):
            self._json({"ok": False, "err": "日期格式须为 YYYY-MM-DD"})
            return
        data5, added5 = analyzer.update_analysis(config.BASE, dates)
        graph.build_graph(config.BASE)                       # v0.8: 分析后自动重建知识图谱
        self._json({"ok": True, "analyzed": added5, "total": len(data5.get("notes", {}))})

    def _post_settings(self, req, st):
        self._json(api.api_post_settings(req if isinstance(req, dict) else {}))

    def _post_patch_done_at(self, req, st):
        self._json(api.api_patch_done_at(req, st))

    def _post_snooze_all(self, req, st):
        self._json(api.api_snooze_all(req))

    def _post_fatigue(self, req, st):
        self._json(api.api_fatigue_toggle(req))

    def _post_mark_reviewed(self, req, st):
        # D-6-1: quality 属业务参数, 转发给 api 层(api_mark_reviewed 有 quality 形参),
        # 而非 _json 响应助手——修复 TypeError(quality= 关键字不匹配)。
        self._json(api.api_mark_reviewed(str(req.get("concept", "")),
                                         quality=req.get("quality")))

    def _post_backup(self, req, st):
        self._json(api.api_backup_now())

    def _post_import(self, req, st):
        self._json(api.api_import(req if isinstance(req, dict) else None))

    def _post_reorder(self, req, st):
        out = services.reorder_tasks(st, req.get("ids") or [],
                                     str(req.get("date") or "") or None)
        if out.get("ok"):
            data.save_tasks(st)
        self._json(out)

    def _post_batch(self, req, st):
        act = str(req.get("action", ""))
        ids2 = [str(i) for i in (req.get("ids") or []) if str(i)]
        ds2 = str(req.get("date") or "") or None
        before = {}
        snapshot = []
        for t in (st.get("days", {}).get(ds2 or config.TODAY) or []):
            tid3 = str(t.get("id"))
            if tid3 in set(ids2):
                if act == "delete":
                    snapshot.append(dict(t))          # 删除类撤销需要整行快照
                else:
                    before[tid3] = t.get("done") if act == "done" else t.get("priority", 2)
        out = services.batch_tasks(st, act, ids2, req.get("value"), ds2)
        if out.get("ok"):
            data.save_tasks(st)
            # Phase C-D: 复习反馈 —— batch done 仅标记「旧未完成 -> 新完成」的复习任务
            # (before 快照在上方已捕获旧 done 值; 转换判定只此一处, 不重复实现)
            if act == "done" and bool(req.get("value", True)):
                for t in st.get("days", {}).get(ds2 or config.TODAY, []):
                    tid4 = str(t.get("id"))
                    if tid4 in before and not before.get(tid4) and t.get("done"):
                        services.maybe_mark_reviewed(t)
            label = {"done": "完成", "snooze": "顺延", "delete": "删除",
                     "priority": "改优先级"}.get(act, act)
            api.log_op({"id": "op-b-" + str(len(st.get("log", []))),
                        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                        "type": "batch_" + act,
                        "label": label + " " + str(out.get("affected", 0)) + " 项",
                        "undone": False,
                        "undo": {"date": ds2 or config.TODAY, "before": before, "snapshot": snapshot,
                                 "ids": ids2, "to_date": out.get("to_date"),
                                 "was_carried": True}})
            try:
                analytics.invalidate_cache(config.BASE)
            except Exception:
                pass
        self._json(out)

    def _post_quick_capture(self, req, st):
        parsed = nl_capture.parse_quick_input(str(req.get("text", "")))
        day_key = parsed.get("day") or config.TODAY
        if day_key == "today":
            day_key = config.TODAY
        elif day_key == "tomorrow":
            day_key = (datetime.datetime.strptime(config.TODAY, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        elif day_key == "dayafter":
            day_key = (datetime.datetime.strptime(config.TODAY, "%Y-%m-%d") + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        bucket = st.setdefault("days", {}).setdefault(day_key, [])
        tid2 = "q-%s-%03d" % (config.TODAY.replace("-", ""), len(bucket) + 1)
        it = {"id": tid2, "text": parsed.get("title", ""), "done": False,
              "carried": False, "src_date": day_key,
              "priority": int(parsed.get("priority") or 2)}
        if parsed.get("est_minutes"):
            it["est_minutes"] = parsed["est_minutes"]
        bucket.append(it)
        data.save_tasks(st)
        api.log_op({"id": "op-qc-" + tid2, "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "type": "quick_create", "label": "创建: " + it["text"][:20],
                    "undone": False, "undo": {"task_id": tid2, "date": day_key}})
        try:
            analytics.invalidate_cache(config.BASE)
        except Exception:
            pass
        self._json({"ok": True, "parsed": parsed, "created_task_id": tid2,
                    "day": day_key, "confidence": parsed.get("confidence")})

    def _post_undo(self, req, st):
        self._json(api.api_undo())

    def _post_firstrun(self, req, st):
        self._json(api.api_firstrun(str(req.get("direction", ""))))

    def _post_help(self, req, st):
        self._json(api.api_help())


__all__ = ["Handler"]
