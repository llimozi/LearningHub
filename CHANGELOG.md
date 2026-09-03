# LearningHub 变更日志

> 更新于 2026-09-03 · 自进化语义一步（v1.13）· analyzer LLM 语义提炼 + route 竞态根治

---

## 【v1.13 · 自进化语义一步 + route 竞态根治（Analyzer LLM & Test Stability）】

- **自进化语义一步（analyzer.py v1.0）** — 概念提炼从「纯词频 top-5」升级为「可选 LLM 语义提炼（3~5 个真核心概念 + 一句话摘要）」，保持**核心零依赖 + AI 可选**：无 Key 时结构与 v0.9 完全一致（纯词频回退）；有 Key 时经 `_call_deepseek`（urllib 直调 deepseek-chat，JSON 模式，temperature 0.2）提炼语义概念并附 `summary` 键。进程级熔断 `_LLM_DISABLED`：任何一次调用失败即熔断回退词频、后续零调用（与 services.weekly_report 同款降级策略）。全系统「理解层」（复习卡、recommender 的 reinforce/review/explore、graph、概念检索索引）自动吃到新 concepts。
- **analyzer_llm_test.py（新增 7 例）** — 全部 mock 注入不触真实 API：无 Key 保持词频 / LLM 成功替换+摘要 / 失败回退+熔断置位 / 坏 JSON 回退 / 熔断后零二次调用 / JSON 容错提取 / 噪音过滤；`_reset_fuse()` 每例复位熔断态。
- **route 竞态根治（route_contract_test.py）** — 根因实证：`http.client` 分步发送（先发头、停顿、再发 body），而服务端对跨源 POST 的 403 拒绝路径「不读 body 即关闭连接」，Windows 下客户端发送 body 撞服务端 RST（WinError 10053），偶发 EXC（修复前基线：route 单跑 9 次 1 失败 ≈11%）。修复：测试客户端改 raw socket **一次性发送完整请求**（模拟真实浏览器连续发送），业务语义零变化；验证 6 进程×60 次 0 失败 + route 单跑 6/6 全绿 + 整套 44 套全绿。
- **routing_test.py 服务端就绪握手** — `_wait_ready` 起服务后循环最小请求至真实响应（3s 超时确定性报错）+ close 显式 socket.close + join serve_forever 线程，消除 Windows 冷启动竞态。
- **终验**：业务测试 **44 套 / 479 例 / 0 失败**（anaconda3 基线运行时）；route_contract_test 单跑 6/6 全绿。

---

## 【v1.12 · UI 视觉与信息架构终章（Quiet Intelligence → UI 冻结）】

- **背景**：Phase UI-A 只读现状审计之后，依次经历 UI-B（Quiet Intelligence 视觉系统）、UI-C（正式图标全面 SVG mask 化，已关闭）、UI-D Stage2（组件打磨）、UI-D Stage3 Stage2（决策中心学习体验）、UI-E Stage1（最终产品只读终审 + 内容卫生批次），至 2026-09-01 达成 UI 冻结条件。此前这一整条 UI 主线**未进 CHANGELOG**，本节补齐。
- **UI-B Quiet Intelligence 视觉系统（`a6e5f4e`）** — 追加 `--qi-*` 字阶 / 间距 / 圆角 / surface 层级 / 交互态 token；sidebar 与 topbar 改实底、main 容器居中 1200px；全卡由 18px 圆角 + 阴影改为 10px 扁平无阴影；`_app/renderer.py` 注入 4 个 `<section>` 语义分组；`#pnl-tasks` 升为**唯一** elevated primary surface。
- **UI-D Stage2 组件打磨（`c99a9bf`）** — 删除死渐变、命令面板遮罩去玻璃拟态、帮助按钮降权、`.btn-mini` 统一 32px / 6px。仅改 `templates/dashboard.css`，6 张 baseline 按 §9 流程更新。
- **UI-D Stage3 Stage2 决策中心学习体验（`95dd8db`）** — 修复总进度显示 `?%`（根因：`STATUS.json` 含 BOM 致 `json.loads` 失败，改用 `data.load_status()` 的 `utf-8-sig`）；复习中心与记忆衰减由并排双面板重构为「下个复习 hero + Up-Next 可排序队列」，**消除 83% 概念重复**；Next Review 直接消费 `forgetting.due_cards` 权威排序（未重排算法）；概念名显示层归一（`_clabel`，`##`→「Markdown 标题」等）；Today 信息序改为 `today → tasks → overview`。
- **UI-E 内容卫生批次（`17c1ad2`）** — 顶栏去掉 `数据源 learning/tasks.json + STATUS.json` 开发者泄漏串；`_reason()` 去重（badge 已表达「已逾期 N 天」，理由串不再重复一遍）。审计第 3 项经源码核对为**误报**（`id="df-close"` 是合法关闭控件），未改动。
- **UI 冻结生效** — 冻结基准为 tag `ui-freeze-2026-09-01`（UI 代码 `17c1ad2` 定稿，终审与实施记录 `20c750f`）；六项不可变契约与例外流程写入 **AGENTS.md §14**。冻结约束的是设计方向与信息架构的再次改版，**缺陷类修复（无障碍 / 对比度 / 焦点 / 数据流 / 文案）不受约束**。
- **终验**：业务测试 **36 套 / 385 例 / 0 失败**（anaconda3 基线运行时）；视觉回归 **18/18 PASS**；契约防线 theme 19 + icon 8 + focus 3 + undo 3 + route 28 + html 14 + floating 5 全绿。

---

## 【v1.11 · Phase 2 治理整改（Governance & Integrity）】

- **背景**：2026-08-31 审查（`refactor_phase2/46`）定位七项问题（并发编辑/图标测试缺口/验收声明失实/VR 基线无证据流程/Task06 归因错误/数据噪音/技术债）；期间遭遇 P0 事件——09:50 并行 ZCode 会话清空 .git 对象库，经用户确认执行抢救式重建（`refactor_phase2/47`）。
- **icon_contract_test.py（新增 7 例）** — 匹配型 `.ni` 图标契约，取代数量下限断言：正向逐元素（每个 .ni 必须匹配含 mask-image 的 CSS 规则）/反向悬空选择器/Task06 全部 8 按钮控件点名/双态切换保留图标/mask 规则总数备案 31。突变验证：移除 `btn-note` id 触发 3 层 FAIL。基线 33 套 371 例 → **34 套 378 例**。
- **run_tests.py 数据防护栏** — 套件前后对运行时数据文件字节级快照 + `.tmp+os.replace` 原子恢复（`_GUARD_FILES`/`_restore_guard`），测试引发的写入自动回滚，消除代码 commit 与数据变更混杂的 Git 噪音。
- **治理规则（AGENTS.md/VISUAL_REGRESSION.md）** — §9.1 baseline 更新纪律（FAIL→人工核 diff→三分类归因→修复后才更新）；§11 验收证据完整性（声明须附测试函数名）；§12 单写入方协议+备份要求；VISUAL_REGRESSION.md §12.1 证据驱动流程含 Task06 归因反例。
- **P0 事件与重建** — 对象库损毁后 `git init -b main` 以工作树重建（T0 指纹证明工作树 100% 完好）；建立 `learning-backups/` bundle 异地备份；损坏 .git 与幸存 130 对象元数据归档。
- **仓库卫生** — `dashboard.html`（可再生快照）出库；工作区根目录 59 项审计残留移入归档；新增 `.gitattributes`（eol=lf 统一，checkout 字节稳定实测 PASS）；README/BACKLOG 同步。

---

## 【v1.10 · 安全与工程运营层修复（Security & Hygiene）】

- **背景**：完成系统性审计（《项目审计报告》A-P 完整结构、加权 6.7/10），定位到三处 P0/P1 问题：本地服务 CSRF 风险、无 git 版本控制、文档与测试现状脱节。阶段 1 修复集中处理。
- **build_dashboard.py · 本地服务 CSRF 防护** — 任何公网页面都可对 `127.0.0.1:8765` 发 fetch 改任务/导入恶意包，已加：
  - 新增 `Handler._check_origin_headers()`：校验 `Origin`/`Referer` host 在 loopback 白名单（127.0.0.1/localhost/::1/0.0.0.0）
  - 写入 API（`do_POST` 入口）增加 403 拒绝路径；`file://` 静态快照视为跨源拒绝
  - 无 Origin 头视为非浏览器放行，保 urllib/curl/本地脚本向后兼容
  - 新增 `csrf_test.py` 13 例覆盖 IPv4/IPv6 loopback、跨源/同源、file/data/javascript 协议、无头兜底、Origin 优先于 Referer
- **build_dashboard.py · POST 体积上限** — `_MAX_POST_BYTES = 10MB` 防 OOM，Content-Length 超限返回 413
- **adaptive_test.py · 软依赖 pytest** — 原文件 `import pytest` 顶层硬依赖，无 pytest 环境直接 ModuleNotFoundError；改为 `try/except` 软依赖，零依赖 runner 仍跑通 12 例
- **git 版本控制基线** — `git init` + `.gitignore`（排除 backup/_archive/__pycache__/*.bak/analytics_cache.json/search_index.json/reports/test_report_*.md）+ 首次提交 92 文件（commit 7dcec86）。后续改动均可回滚
- **_archive/_build_artifacts 软删** — 375MB PyInstaller 历史产物重命名为 `_build_artifacts_DEPRECATED_20260830`（可后续硬删，git 不受影响）
- **README 文档同步** — 测试数字更新为"27 套 294 例（系统 Python 含 tkinter）/ 270 例（managed Python 缺 tkinter）"；新增环境差异说明
- **测试** — csrf_test.py 13 例全绿；`run_tests.py` 27 套 / **294 例 / 失败 0**（系统 Python 3.13.13）；managed Python 3.13.12 跑出 270 例 / 1 失败（仅 resident_test 因 tkinter 缺失，非代码问题）

---

## 【v2.5 · UI/排版全面重构（Premium / Sleek · Apple 式质感）】

- **背景**：v2.4 毛玻璃虽已透通，但用户反馈「效果一般、还是像毛胚房」——诊断达标但字号偏小(正文14px)、emoji 当图标、无单点焦点、主色通用、留白不足。本次用 styleseed / premium / sleek 方法论做一次**真正的全面重构**，全部视觉改在 CSS 样式层追加，零改 DOM/JS 结构类。
- **templates/dashboard.css** — 新增 v2.5 高级克制层（叠在 v2.4 玻璃层之上，末位覆盖生效）：
  - **桌面字号基准**：正文 `14px→16px`、行高 `1.7`，数字/进度等宽 `tabular-nums`
  - **字体锁定**：`Inter/SF Pro/微软雅黑` + 数字代码 `JetBrains Mono`
  - **留白呼吸**：内容宽 `1480→1360`、间距 `18→26`、卡片内边距统一
  - **单一焦点**：首屏总览 hero 卡主导（高光渐变+专属描边+大数字渐变），打破全网格同权重
  - **emoji→矢量图标**：左导航 8 个 `.ni` 图标改 `mask-image` 内联矢量线条（Feather 风格），按 `href` 精准分配
  - **状态色克制**：正常/中性回灰；卡片/浮层细描边+顶部高光
- **theme.py** — 三套主题 `--accent`/`--accent-hov` 微调为更透亮的蓝/蓝紫（只改值，17 变量名/顺序/hex 格式不变，契约完好）
- **ui_refactor_test.py** — 扩展至 14 例（新增 v2.5 层存在 / emoji 换矢量图标 / hero 焦点 / 内容宽收拢 / 状态色克制）
- **测试**：`ui_refactor_test.py` 14 例 + `theme_test.py` 10 例全绿；`run_tests.py` 全套 **26 套 / 281 例 / 失败 0**。
- **说明**：`.ni` 非导航图标（命令面板/帮助页 emoji）保留（属帮助/装饰语义）；静态 `dashboard.html` 快照已含 v2.5；**运行中的服务器因进程级 CSS 缓存需重启才显示新设计**。

---

## 【v2.4 · UI 毛玻璃重构（Glassmorphism）】

- **目标**：用下载的设计 Skills 方法论（styleseed / hue / awesome-design-skills / superdesign），把仪表盘从「功能完备但视觉朴素」升级为现代通透的毛玻璃质感，同时保留三套主题与全部交互。
- **templates/dashboard.css** — 新增 v2.4 玻璃拟态层（L5）：
  - **背景光斑**：主区铺柔和多层径向渐变（强调色/成功色/警示色微光），作为玻璃「透过去」的风景
  - **玻璃表面**：侧栏/顶栏/卡片/浮层改半透明 + `backdrop-filter: blur+saturate` + 半透明细边框 + 顶部高光，「一层膜」的通透分层
  - **优雅降级**：全部玻璃规则包在 `@supports (backdrop-filter: blur(1px))` 内，不支持背景模糊的浏览器回落 `v2.2` 实体色，不白屏
  - **主题零冲突**：半透明一律用 `color-mix` 从既有主题变量派生，**不新增/改名任何主题变量**（`theme_test.py` 的 17 变量契约完好）
- **排版与状态规整**（纯样式，不改 DOM/JS 选择器）：
  - 字重归一：杂牌 `650/750` 覆盖为统一四档 `400/500/600/700`
  - 圆角统一：按钮/子卡/提示卡统一到语义圆角（卡片 12px）
  - 补齐输入框 `hover` / `focus-visible` 聚焦环与 `::placeholder` 弱化色（此前缺失）
- **ui_refactor_test.py**（新增）— 9 例不变量测试：玻璃层存在 / 半透明玻璃面 / @supports 降级包裹 / 字重归一 / 圆角统一 / 输入聚焦环 / JS 结构类保留 / L4 稳定边界完好 / 主题契约未动
- **READ ME「设计系统」** 节扩展到 v2.0–v2.4，新增 v2.4 玻璃拟态层说明
- **说明**：所采用的 4 个设计 Skills 中，superdesign 仅取其「读代码库取上下文防 AI-slop」方法论（其云端 CLI 需登录，不适用本项目）；styleseed / hue / awesome-design-skills 作为设计评审清单与风格参考。
- **测试**：`ui_refactor_test.py` 9 例 + `theme_test.py` 10 例全绿；`run_tests.py` 全套 26 套 / 276 例 / 失败 0。

---


## 【已修复 - 致命】

### 1. `build_dashboard.py` — 非原子写入 → 原子写入
- **函数**: `save_tasks(st)`、`save_status(data)`
- **修改**: 先写 `.tmp` 临时文件 → `os.replace()` 原子替换
- **风险消除**: 写入中途断电不再损坏 JSON，避免学习数据全部丢失
- **同步**: `touch_last_open()` 中的 STATUS.json 写入也一并修复

### 2. `transfer.py` — 部分写入 → 事务式全有或全无
- **函数**: `import_bundle(learning_dir, bundle, now=None)`
- **修改**:
  - 第一步：备份
  - 第二步：纯内存合并（不碰磁盘）
  - 第三步：全部合并成功后才执行原子落盘
  - 失败时：从 `.import_bak` 文件级备份恢复所有已写的文件
- **风险消除**: 不再出现「tasks.json 已改、knowledge.json 未写」的新旧混合状态

---

## 【已优化 - 性能】

### 3. `search.py` — 全量重建 → 增量更新
- **函数**: `update_note(learning_dir, date)`
- **新增**: `_doc_tokens()`、`_remove_doc_from_index()`、`_add_doc_to_index()`
- **修改**:
  - 倒排表更新：从遍历全部 token → 仅 diff 变化的 token
  - 标签文档：从重扫全部笔记 → 仅添加新标签
- **复杂度**: O(全量文档 × 全量分词) → O(单篇分词 + 倒排局部更新)

### 4. `build_dashboard.py` — 重复 I/O → 单次读取
- **函数**: `api_daily_focus()` → 拆分为 `api_daily_focus()` + `_focus_impl(st, a)`
- **效果**: `tasks.json` 读取 4→1 次，`knowledge.json` 读取 3→1 次

---

## 【已重构 - 架构】

### 5. `build_dashboard.py` — CSS 内联 → 外部文件
- **修改**: ~855 行 CSS 提取到 `templates/dashboard.css`
- **新增**: `_read_dashboard_css()` 带缓存读取
- **效果**: `build_dashboard.py` 行数 4063→3254（减少 20%），Python 逻辑清晰可见

### 6. `build_dashboard.py` — 模糊路由 → 精确路由
- **新增**: `Handler._match_route(path, route)` 静态方法
- **匹配规则**: 完全相等 / 后接 `?` / 后接 `/`
- **替换**: 39 个 `self.path.startswith("/api/xxx")` → `self._match_route(self.path, "/api/xxx")`
- **风险消除**: `/api/stateful` 不再误匹配 `/api/state`

---

## 【已规范 - 代码】

### 7. 编码统一：全部 JSON 文件使用 `utf-8-sig`
- **涉及**: settings.py、transfer.py、search.py、backup.py、analytics.py、forgetting.py、analyzer.py、graph.py、reportio.py、firstrun.py、weakspot.py、tag_notes.py、build_dashboard.py
- **效果**: 兼容记事本编辑（BOM 头标识），读写一致无乱码

### 8. 全局日志配置
- **涉及**: `build_dashboard.py:main()`、`resident.py:main()`
- **新增**: `_setup_logging()` → `app.log`（ERROR 级别，UTF-8 编码）
- **效果**: 错误不再静默丢失

### 9. 测试文件同步更新
- **涉及**: 11 个测试文件（planner_test.py、settings_test.py、analytics_test.py、mastery_test.py、reminders_test.py、resident_test.py、theme_test.py 等）
- **修改**: 读写 JSON 统一使用 `utf-8-sig`

---

## 测试验证

| 测试套件 | 结果 |
|----------|------|
| 全部 22 个测试文件 | **239/239 PASS** |
| `build_dashboard.py --selftest` | PASS |
| `transfer_test.py` 事务回滚专项 | PASS |
| 路由精确匹配专项 | 15/15 PASS |

---

## 文件变更清单

| 文件 | 变更类型 |
|------|----------|
| `build_dashboard.py` | 致命修复 + 性能优化 + 架构重构 + 规范 |
| `transfer.py` | 致命修复 + 规范 |
| `search.py` | 性能优化 + 规范 |
| `settings.py` | 规范 |
| `backup.py` | 规范 |
| `analytics.py` | 规范 |
| `forgetting.py` | 规范 |
| `analyzer.py` | 规范 |
| `graph.py` | 规范 |
| `reportio.py` | 规范 |
| `firstrun.py` | 规范 |
| `weakspot.py` | 规范 |
| `tag_notes.py` | 规范 |
| `resident.py` | 规范 |
| `templates/dashboard.css` | 新增（从 build_dashboard.py 提取） |
