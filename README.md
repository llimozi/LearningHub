# LearningHub · 学习仪表盘 —— 自进化学习系统的桌面常驻 APP

🔒 **Runtime: Python stdlib only** · 🤖 **AI Enhancement: optional**（DeepSeek API，无 Key 自动降级）

> 一句话：把学习档案（ROADMAP/PROFILE/daily）和任务数据（tasks.json）变成一个可交互的本地仪表盘——勾选实时写回、日切自动顺延、疲劳检测、优先级分流、明日量预测；桌面常驻：托盘图标、开机自启、本地提醒、全局热键；数据闭环：自动备份、导入导出、遗忘曲线复习、周报月报；体验打磨：三主题即时换肤、Ctrl+K 全文搜索、键盘流与拖拽批量。**核心运行零第三方依赖**；仅 AI 周报润色为**可选增强**（需自备 DeepSeek API Key，未配置时自动降级为本地模板）。

## 功能截图（占位）

<!-- 截图待人工验收时补齐, 建议四张: -->
<!-- ![仪表盘总览](docs/shot-dashboard.png) -->
<!-- ![知识图谱](docs/shot-graph.png) -->
<!-- ![托盘常驻](docs/shot-tray.png) -->
<!-- ![Ctrl+K 搜索](docs/shot-search.png) -->

## 目录结构

```
LearningHub/
├─ 启动常驻版.bat        ★v1.0 推荐：双击拉起常驻壳（pythonw 无黑窗，缩到托盘）
├─ 打开学习仪表盘.bat    传统入口：起服务+自动开浏览器（关窗=停服务），仍兼容
├─ resident.py           v1.0 常驻壳编排：单实例检测/服务线程/Tk控制窗/托盘/提醒调度
├─ build_dashboard.py    主程序：服务入口 + 快照导出（render/API/Handler 已拆入 _app/，D-5）
├─ _app\                 服务层（D-5/D-6 拆分，原 build_dashboard.py 主体）
│   ├─ server.py         HTTP 服务：GET_ROUTES(25)+POST_ROUTES(19) dispatch 表 + CSRF/10MB 防线（D-6）
│   ├─ renderer.py       render() 纯装配（183 行，D-5d）
│   ├─ render_templates.py  25 个 _tpl_* 纯模板函数
│   ├─ render_data.py    build_context 数据准备（ViewModel，D-5c）
│   ├─ api.py / services.py / data.py / config.py   API 本体 / 业务原语 / 数据层 / 配置
├─ planner.py            规划引擎：history统计 / 疲劳检测 / 优先级 / 明日预测
├─ analyzer.py           v0.7 笔记语义分析（jieba 可选）+ 复习状态机
├─ graph.py              v0.8 共现图谱构建（节点/边/核心概念）
├─ recommender.py        v0.9 路径推荐（rest/review/explore 三规则, 纯规则无 LLM）
├─ heatmap.py            v0.6 热力图数据模块（daily 扫描/365天分档）
├─ settings.py           v1.0 设置中心：settings.json 读写(原子落盘) + 注册表自启封装
├─ reminders.py          v1.0 提醒引擎：每日首开/复习临近/连续未打开 三判定+动态文案
├─ tray.py               v1.0 托盘与热键：纯ctypes(Shell_NotifyIconW/RegisterHotKey) + ICO手写生成
├─ backup.py             v1.1 自动备份：24h窗口判定 / zip压缩 / 保留14份轮转
├─ transfer.py           v1.1 导入导出：校验→自动备份→合并(同id覆盖/新id追加)
├─ forgetting.py         v1.1 遗忘曲线引擎：艾宾浩斯间隔×SM-2掌握系数 / 今日待复习 / 保持率
├─ reportio.py           v1.1 周报月报：四要素聚合 / 手绘SVG四周趋势 / 周一锚定幂等生成
├─ adaptive.py           v1.2 节奏自适应：连高日加量/连低日减量+休息建议, 参数全可调
├─ mastery.py            v1.2 掌握度模型：四因子0~100分, 新概念保护期, 重点攻克队列
├─ weakspot.py           v1.2 周日薄弱点分析: 最低5概念专项练习自动插入下周任务库
├─ search.py             v1.3 全文搜索: CJK二元组倒排索引/mtime缓存复用/增量更新/高亮片段
├─ theme.py              v1.3 主题系统: 三套暗色主题CSS变量末位覆盖层, 即时换肤
├─ paths.py              v1.4 打包态路径解析(源码态=脚本目录/exe态=所在目录)
├─ build.py              v1.4 一键打包: 环境校验→自制图标→PyInstaller参数拼装→产物报告
├─ firstrun.py           v1.4 首次运行: 缺失结构初始化 + 八周路线图骨架生成
├─ helpcenter.py         v1.4 内置帮助: 快捷键/功能/FAQ/备份指引 四板块Markdown
├─ editor.html           笔记编辑器（/editor 打开：双栏+实时预览+标签注入）
├─ settings.json         v1.0 设置真源（自启偏好/提醒偏好/主题; 首次运行自动生成）
├─ daily\analysis.json   知识点台账（按日期去重自动追加）
├─ daily\knowledge.json  v1.1 记忆档案：每概念 last_review_ts/review_count/ease_factor
│                        + review_log 复习流水 + mastery_score 掌握分(v1.2)
├─ daily\graph.json      图谱落盘（nodes/edges/summary）
├─ backup\               v1.1 自动备份 zip（≤14份）+ meta.json
├─ reports\              v1.1 正式报告: 周报 / 月报 / 趋势SVG / 薄弱点分析（可再生, 不进备份）
├─ tests_output\         D-11 测试报告: run_tests.py 自动生成（独立于 reports, 不进备份）
├─ search_index.json     v1.3 全文搜索倒排索引缓存（源变化自动重建）
├─ run_tests.py          v1.4 一键测试: 发现全部 *_test.py 逐套执行, 报告落 tests_output\
├─ health_check.py       v1.4 自检: 数据完整性/JSON可解析/磁盘空间/端口/备份 九项检查
├─ stoplist.txt          停用词表（每行一词, 可自行扩充）
├─ STATUS.json           总览状态（总进度/打卡/复习点/last_open_ts），每轮收尾更新
├─ tasks.json            ★任务真源：分天桶 + history + fatigue（服务运行时勿手改）
├─ dashboard.html        静态快照导出物（--no-open 生成，只读；2026-08-31 起出库不入 git，见 .gitignore）
├─ PROFILE.md / ROADMAP.md / SOURCES.md / REVIEW.md / BACKLOG.md   档案五件套+待办池
├─ lessons_learned.md    v1.x 踩坑档案（BOM/钳制/读写不对称/pack重复/幂等键名…）
├─ 项目成果盘点.md        成果盘点文档（每版本更新）
├─ *_test.py             43 套测试共 472 用例（系统 Python 3.8+ 含 tkinter 全绿；managed Python 缺 tkinter 时 resident_test 收集失败）；pytest 与零依赖 runner 双通道
│                        routing_test.py(7) 结构契约 + route_contract_test.py(28) HTTP 行为契约（D-6-0）
└─ daily\YYYY-MM-DD.md   每日日志（当日 checkbox 仅作 tasks.json 初始化种子）
```

## 快速开始

### 方式零：直接运行 exe（v1.4 打包后）

1. 双击 `dist\LearningHub.exe`——数据自动生成在 exe 同目录，拷去哪都能用
2. 首次启动弹三步引导：常驻说明 → 每日打卡 → 填学习方向（自动生成八周路线图骨架）
3. 自检：`health_check.py`；一键测试：`run_tests.py`

### 方式一：桌面常驻（推荐开发态）

1. 双击 `启动常驻版.bat`——控制窗出现在右下角，任务栏通知区出现蓝底对勾托盘图标
2. 托盘**左键单击**=唤起/看控制台 ｜ **右键**=菜单（打开主界面 / 快速记录今日完成 / 隐藏 / 退出）
3. 全局热键 **Ctrl+Shift+L**=呼出/隐藏控制台（被其他软件占用时自动降级，托盘仍可用）
4. 控制窗**点关闭=缩到托盘**不退出；真退出只认托盘菜单「退出」
5. 开机自启：仪表盘页面底部「⚙️ 设置」卡 → 点「开机自启」按钮（写注册表 HKCU Run 键，值名 LearningHub；再点一下即关闭）
6. 提醒：每日首次开机 / 复习时段（默认20:00）前30分钟 / 连续2天未打开，文案从任务库与知识点台账实时生成

### 方式二：传统网页版

1. 双击 `打开学习仪表盘.bat`（自动找 python，找不到用 py）
2. 浏览器打开 `http://127.0.0.1:8765/`（端口被占自动+1）
3. 操作：**点复选框**=勾选（实时存盘）｜ **右键任务**=设优先级 P1/P2/P3 ｜ **立即收尾按钮**=顺延未完成+生成明日计划
4. 关闭黑窗口 = 服务停止

> 常驻壳单实例：已在跑时再次双击 bat 只会新开一个仪表盘页面，不会出现双托盘图标。
> 已知限制：常驻进程跨零点后当日任务桶不自动切换，重启应用即可（日切顺延逻辑不受影响）。

## tasks.json schema（v0.3 速览）

```jsonc
{
  "version": 3,
  "days": { "<YYYY-MM-DD>": [ {        // 任务按日期分桶
      "id": "t-20260822-01",           // 稳定ID
      "text": "任务名",
      "done": false,                   // 完成状态
      "carried": false,                // 顺延标记
      "defer2": false,                 // 疲劳模式 P2 专属：延后2天
      "src_date": "2026-08-22",        // 原始归属日
      "priority": 2 } ] },             // 1高 | 2中 | 3低，缺省自动补2
  "history": [                         // 收尾自动追加，保留最近30天
    { "date": "…", "total": 3, "done": 1, "rate": 0.3333 } ],
  "fatigue": { "active": false, "since": null, "reason": "" },
  "log": [ { "date": "…", "event": "rollover|drop_p3|init" } ]
}
```

## planner.py API

| 函数 | 作用 |
|---|---|
| append_history(state, date, total, done) | 记录当日完成率，裁剪保留30天 |
| get_stats(state) | 7日/30日平均完成率 + 最长连续达标(rate≥0.8)天数 |
| detect_fatigue(state) / is_fatigued(state) | 疲劳判定：连续3天<50%触发，单日≥80%解除 |
| normalize_priorities(state) | 给缺 priority 的任务补默认值 |
| sort_for_defer(tasks) | 高优先级在前（稳定排序） |
| fatigue_split(undone, fatigued) | 疲劳分流：P1滚明天 / P2延后2天 / P3丢弃 |
| lin_slope(ys) | 最小二乘斜率（x=0..n-1） |
| predict_tomorrow(state) | 明日建议 = round(近7日均完成 × (1+slope±0.3))，疲劳受 cap=max(3,均完成×0.8) |
| finalize_day(state, date) | 收尾编排：记历史→判疲劳→统计→预测 |

## settings.json schema（v1.0）

```jsonc
{
  "version": 1,
  "autostart": false,                // 自启偏好(注册表为实际生效状态, 二者由接口同步)
  "theme": "dark",                   // dark | midnight-blue | ink-green（v1.3 起生效）
  "reminders": {
    "daily_first_open": true,        // 每日首次开机提醒
    "review_near": true,             // 复习临近提醒(复习时段前30分钟)
    "review_time": "20:00",          // 今日复习时段
    "away_nudge": true,              // 连续未打开回归提醒
    "away_days": 2,                  // 「未打开」天数阈值
    "fired": { "<日期>": ["daily","review","away"] }   // 当日已弹记录, 自动清理
  }
}
```

STATUS.json 新增字段：`last_open_ts`（本次打开时刻；旧值快照用于「连续未打开」判定）。

## v1.0 新增 API

| 端点 | 说明 |
|---|---|
| GET /api/settings | 返回 `{settings, autostart_registered}`（注册表登记命令或 null） |
| POST /api/settings | 深合并补丁落盘；`autostart` 翻转时同步写/删注册表，失败走 `autostart_error` 字段不炸接口 |

## v1.1 新增 API（数据闭环）

| 端点 | 说明 |
|---|---|
| GET /api/due_reviews | 今日待复习队列（同步记忆档案→按保持率升序，≤12 条） |
| POST /api/mark_reviewed `{concept}` | 复习打卡：次数+1、时间戳更新、ease 随默认质量4微调 |
| GET /api/retention | 记忆衰减卡数据（全概念保持率升序 ≤20 行） |
| GET /api/export | 单文件 JSON 导出（Content-Disposition 触发浏览器下载） |
| POST /api/import | 导入整包：校验→自动备份→同id覆盖/新id追加，台账变更后图谱重建 |
| POST /api/backup | 手动立即备份（同 24h 自动备份同一套轮转） |
| GET /api/reports/list | reports\ 目录清单（名字降序） |
| GET /api/report?name=xx.md | 报告正文；纯文件名校验，拒路径穿越 |

仪表盘三张新卡：**🧠 今日待复习**（打卡按钮）｜ **📉 记忆衰减**（绿≥70/黄40~69/红<40 渐变条）｜ **📄 报告**（在线预览，月报内联趋势 SVG）。设置页新增导出/导入/立即备份。

## v1.2 新增（智能增强）

| 项 | 说明 |
|---|---|
| settings.json `adaptive` 块 | `{enabled, high_rate:0.9, high_run:3, boost:0.10, low_rate:0.5, low_run:2, reduce:0.20}`——设置页可视化调参 |
| GET /api/mastery | 全概念掌握分 + 重点攻克队列（<40 分） |
| 状态概览卡徽标 | 明日建议条数 = 引擎预测 × 自适应系数，⚡加量/🛟减负带一句话原因 |
| 图谱节点配色 | 按掌握分：红<40(粗描边) / 黄40~69 / 绿≥70 越高越实；悬停显示分数 |
| 推荐第四规则 reinforce | 存在 <40 概念时置顶补弱，理由=掌握分+未复习天数+遗忘风险%；rest 健康保护仍第一 |
| 周日自动分析 | 启动钩子在周日跑 weakspot.weekly_analysis：最低5概念→专项练习(P1)插入下周任务库，报告落 reports\weakness_下周周一.md |

## v1.3 新增（体验打磨）

| 项 | 说明 |
|---|---|
| 三套暗色主题 | 深空灰(默认) / 午夜蓝 / 墨绿——CSS 变量末位覆盖层实现，设置页下拉**即时换肤不刷新**，选择持久化；编辑器同步换装 |
| Ctrl+K 全文搜索 | 覆盖任务标题/笔记正文/知识点/标签；CJK 二元组倒排索引(search_index.json 缓存+源mtime复用+保存增量更新)；结果按相关度排序、片段高亮、点击直达 |
| 键盘流 | 任务列表 ↑↓移动 / Space 勾选 / Enter 展开详情；Ctrl+1~4 切换 任务·图谱·待复习·设置 四面板 |
| 拖拽与批量 | 原生拖拽排序(/api/reorder)；Shift 多选 → 批量完成/删除/改优先级(/api/batch) |
| 空状态与引导 | 六款 SVG 插画空状态；首次运行三步引导浮层(guide_done 标记)，设置页可重看 |

## 测试

```bash
python run_tests.py                        # 一键测试: 自动发现 *_test.py, 报告落 tests_output\
python -m pytest -q                        # 全量 472 例 (43 套; 系统 Python 3.8+ 含 tkinter)
python build_dashboard.py --selftest       # rollover 三规则回归(隔离数据)
python resident.py --smoke-exit            # 常驻壳冒烟: 全组件真跑5秒自退, ExitCode=0 为过
python csrf_test.py                        # 本地服务 CSRF 防护回归 (v1.10)
python route_contract_test.py              # D-6-0 路由 HTTP 行为契约 (28 例)
python diagnose_mark_reviewed.py           # D-6-1 mark_reviewed bug 诊断(独立, 不进主套件)
```

> **环境差异说明**：系统 Python 3.8+ 含 tkinter 时跑 **43 套 / 472 例 / 失败 0**；
> managed/sandbox Python 若未带 tkinter（如某些便携发行版），resident_test 收集失败，**仍能跑 461 例**；
> 任何环境变更请以 `python run_tests.py` 实际输出为准。

## 依赖

- **核心运行**：Python 3.8+ **标准库即可跑通全部功能**（🔒 Runtime: Python stdlib only，零第三方运行时依赖）
- **可选增强①（AI 周报润色）**：设置环境变量 `DEEPSEEK_API_KEY` 后启用 DeepSeek API；**未配置 Key 自动降级本地模板**，功能不缺（🤖 AI Enhancement: optional）
- **可选增强②（中文分词）**：`pip install jieba`（更准；未装时 analyzer 自动回退 n-gram 词频，功能不缺）
- 国内网络建议加镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`
- pytest 仅测试需要：`pip install pytest`（或直接跑 `python planner_test.py`）

## 版本史

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.10 | 2026-08-30 | 安全与工程运营层修复：本地服务 CSRF 防护（`_check_origin_headers` + 13 例 csrf_test.py）+ POST 体积上限 10MB / 413 / git init 基线（commit 7dcec86，92 文件，.gitignore 排除 backup/_archive/cache） / adaptive_test 软依赖 pytest 改零依赖 runner / _archive/_build_artifacts 软删 375MB / README 测试数字与实测同步 |
| v0.1 | 2026-08-22 | 静态渲染最小版：md→html、STATUS.json 头部大数字、自动开浏览器 |
| v0.2 | 2026-08-22 | 勾选写回 tasks.json + 日切自动顺延三规则 + 本地服务交互模式 |
| v0.3 | 2026-08-22 | planner.py 智能规划引擎（history/疲劳/优先级/预测）+ /api/stats /api/tomorrow /api/priority 三端点 |
| v0.4 | 2026-08-22 | UI 现代化：常驻暗色 / SVG 完成环 / 7日柱状 / 划线动画 / 右键菜单 / 响应式 |
| v0.5 | 2026-08-22 | 知识资产化：editor.html 笔记编辑器（实时预览+标签）/ 📚知识库面板 / POST /api/save_note·load_note·notes |
| v0.6 | 2026-08-22 | 深度复盘：heatmap.py 学习热力图(GET /api/heatmap) / AI 周报(POST /api/weekly_report, DeepSeek 可选+本地模板降级) / 一键复制 |
| v0.7 | 2026-08-22 | 语义分析：analyzer.py 提取知识点(jieba 可选) / 🧠待复习卡片(新学·需复习·已巩固状态机) / POST /api/analyze · GET /api/review_cards / 编辑器保存联动分析 |
| v0.8 | 2026-08-22 | 概念图谱：graph.py 共现网络(daily/graph.json) / SVG 力导向图(斥力+引力×100迭代, top30防卡顿) / 节点颜色随复习状态 / 点击跳笔记·可拖拽 / GET /api/graph |
| v0.9 | 2026-08-22 | 噪声根治(analyzer 三层过滤+stoplist.txt 可扩充) + 学习路径推荐 recommender.py(rest/review/explore 三规则, GET /api/recommendations, 实时计算) |
| v1.0 | 2026-08-23 | 桌面常驻化：resident.py 常驻壳(单实例+服务线程+Tk控制窗) / tray.py 纯ctypes托盘+Ctrl+Shift+L热键+ICO手写生成 / settings.py 设置中心(原子落盘+注册表自启) / reminders.py 三触发提醒(文案动态生成+fired防重弹) / 设置页卡片 / GET·POST /api/settings / STATUS.last_open_ts / 启动常驻版.bat |
| v1.1 | 2026-08-23 | 数据闭环与遗忘曲线：backup.py 自动备份(24h窗口+zip轮转14份) / transfer.py 导入导出(校验→备份→合并,图谱联动重建) / forgetting.py 遗忘曲线引擎(艾宾浩斯1/2/4/7/15/30×SM-2系数,记忆档案knowledge.json,今日待复习队列) / reportio.py 周报月报(SVG手绘趋势,周一锚定幂等) / 三张新卡(待复习·记忆衰减·报告预览) / 8个新接口 / 启动备份与报告钩子 |
| v1.2 | 2026-08-23 | 智能增强与自适应：adaptive.py 节奏自适应(连3天≥90%次日+10%,连2天≤50%次日-20%+休息建议,参数存settings.adaptive可调) / mastery.py 掌握度模型(四因子0~100写回mastery_score,新概念保护期,<40进重点攻克队列) / weakspot.py 周日薄弱点分析(最低5概念专项练习确定性id插入下周库) / recommender 第四规则reinforce补弱优先(理由含掌握分/间隔/遗忘风险%) / 图谱按掌握分配色 / GET /api/mastery / 设置页自适应参数区 |
| v1.3 | 2026-08-23 | 体验打磨：theme.py 三套暗色主题(深空灰/午夜蓝/墨绿,CSS变量末位覆盖层,下拉即时换肤不刷新,编辑器同步) / search.py 全文搜索(CJK二元组倒排索引+search_index.json缓存+保存增量更新+相关度高亮) / Ctrl+K搜索浮层 / 键盘流(↑↓·Space·Enter·Ctrl+1~4) / 原生拖拽排序(/api/reorder)+Shift批量(/api/batch:完成·删除·优先级) / 六款SVG空状态插画 / 首次运行三步引导(guide_done) / 修复v0.x遗留虫2只(收尾按钮未渲染·__REVIEW__同名复用错乱,新增占位符零残留断言) |
| v1.4 | 2026-08-23 | 打包分发：paths.py 打包态路径解析(exe旁数据,防_MEI临时目录丢数据)+asset_path资源分流 / build.py 一键打包(环境校验·自制三尺寸图标·--onefile --noconsole --add-data·产物体积报告,输出dist/LearningHub.exe) / firstrun.py 首次运行(缺失结构初始化+按方向生成八周路线图,/api/firstrun接通引导最后一步) / helpcenter.py 内置帮助(快捷键/功能/FAQ/备份指引四板块,/api/help复用渲染管线+❓帮助卡) / run_tests.py 一键测试(21套239例自动发现+Markdown报告) / health_check.py 九项自检(退出码只看硬失败) / README终稿+CHANGELOG全量日志 |

## 📊 数据智能（v1.6 · analytics.py）

> 目标：让系统主动回答「该怎么学」。三个指标全部本地计算、纯标准库零依赖；`GET /api/analytics` 异步加载不阻塞首屏；结果带 mtime+TTL 双重缓存(analytics_cache.json)，源数据一变即自动重算。

### 1️⃣ 认知负荷指数 CLI（0~100）—— 今天这副担子会不会压垮我？
- **公式**：`CLI = clamp(0..100, (55×负荷比 + 25×欠账率 + 20×连排压力) × 疲劳加成)`
  - 负荷比 = 今日加权任务量 ÷ (近7天日均加权消化量×2)；优先级权重 P1=1.5 / P2=1.0 / P3=0.7
  - 欠账率 = 今日未完成任务占比；连排压力 = min(连续欠账天数, 7) ÷ 7
  - 疲劳加成 = planner.detect_fatigue() 激活时 ×1.25
- **分区与建议**：≤35 轻松(可加挑战) ｜ ≤60 适中(先清旧账) ｜ ≤80 偏重(别再加新内容) ｜ >80 过载(只保 P1，其余顺延)
- **可视化**：大数字 + 单色分段进度条，颜色随分区切换(绿→蓝→黄→红)

### 2️⃣ 知识稳固度（按标签聚合保持率）—— 哪块知识开始漏水了？
- **公式**：概念级 R = exp(-间隔 ÷ (有效复习间隔×1.6))，完全复用 forgetting.py 的 SM-2/艾宾浩斯引擎；按笔记标签聚合取均值，**最薄弱的排最前**
- **数据源**：daily/knowledge.json(记忆档案) × daily/analysis.json(概念↔日期↔标签)；无标签概念归入「未分类」不会丢失
- **可视化**：横向色条行(绿≥70 / 黄40~69 / 红<40)，底部给出最薄弱领域行动提示
- **使用建议**：红区标签的卡片优先刷；daily 笔记认真写 `tags:` 行可让聚合更精准

### 3️⃣ 最佳专注时段 —— 高难任务该排在几点？
- **数据源**：任务勾选时刻 done_at(**v1.6 起 toggle 自动记录**，取消勾选即作废重记)
- **诚实约定**：完成时刻样本 <20 次时只显示「数据采集中」，绝不下结论；正常学习约两周解锁
- **可视化**：七个时段(清晨06-09/上午09-12/午间12-14/下午14-17/傍晚17-20/夜间20-24/深夜00-06)完成次数分布条，峰值时段高亮
- **使用建议**：解锁后把最难的新知识排进高峰时段，机械性事务放在低谷期

### 已知边界（诚实声明）
- ~~任务暂无结构化的「预估/实际耗时」字段~~ **v1.8 已落地**：daily 任务里写「≤45min / 约30分钟 / 1-1.5h」会自动识别为 est_minutes 并显示 ⏱ 徽章；补录浮层可顺手填实际用时(actual_minutes)，积累 ≥5 次采样后「⏱ 本周时间预算」给出计划 vs 现实对比
- ~~稳固度只用保持率~~ **v1.8 已消费 review_log**：按复习质量加权(半衰期30天衰减)，「复习了但质量不高」的概念打 ⚠️ 并在钻取中显示评分

### 🎨 设计系统（v2.0–v2.5）
- 所有视觉参数收敛到 `:root` 设计令牌：`--space-*`(4px 基线间距)、`--text-*`(六级字号)、`--radius-*`、`--shadow-*`、`--duration-*`+`--ease-*`(动效)；颜色类令牌是主题变量的「别名」，切换深空灰/午夜蓝/墨绿主题时整套设计语言同步变色
- 排版：正文 letter-spacing .01em、数字一律 tabular-nums 对齐、层级靠字号字重而非颜色(Linear 式克制)
- 动效：只动 transform/opacity，120/200/350ms 三档时长+out/in-out/spring 三种缓动，尊重 prefers-reduced-motion
- **v2.1 视觉升级层**：卡片投影/表面线/焦点环令牌，任务卡按 `data-pri` 显示优先级左边框，1240/920/640px 三档响应式断点（对标 Pico/Simple.css/Water.css 的克制语言，零外部依赖）
- **v2.2 主题兼容修正层**：修复升级层与末位主题覆盖层的层叠冲突，三套主题观感一致
- **v2.3 表单全面接令牌**：设置卡 select/time/number 输入、分隔线、保存按钮与知识图谱连线全部去硬编码色，换主题完全跟色
- **v2.4 玻璃拟态层**：主表面(侧栏/顶栏/卡片/浮层)改为半透明 + `backdrop-filter` 背景模糊，主区铺柔和主题光斑——现代通透分层；全部用 `color-mix` 从主题变量派生半透明、不新增主题变量，`@supports` 包裹保证不支持背景模糊的浏览器回落实色不白屏；同步统一字重(650/750→四档)、统一圆角、补齐输入框聚焦环与 hover 态
- **v2.5 高级克制层（Premium / Sleek，Apple 式质感）**：全部视觉改在样式层追加，零改 DOM/JS 结构类——
  - **桌面 B2B 字号基准**：正文 `16px`、行高 `1.7`（原 `<14px` 移动端紧凑档，桌面显得小挤）；数字/进度一律等宽 `tabular-nums`
  - **字体锁定**：正文 `Inter/SF Pro/微软雅黑` 回退系统族；数字/代码用 `JetBrains Mono` 回退 `Cascadia Code`
  - **留白呼吸**：内容宽 `1480→1360px`、区块间距 `18→26px`、卡片内边距统一 `22-26px`
  - **单一焦点**：首屏总览 hero 卡做主导区（更强高光渐变 + 专属描边 + 大数字渐变），打破「全网格同权重」
  - **主色升级（更清透蓝紫）**：三套主题 accent 微调为更透亮的蓝/蓝紫，文字对比度保持 ≥4.5:1
  - **emoji→矢量图标**：左导航 8 个 `.ni` 图标（原 `📈🎯🔥🧠🕸️✨📚⚙️`）改用 `mask-image` 内联矢量线条图标（Feather 风格），按 `href` 精准分配，纯 CSS 零 JS 改动、未匹配项自动保留 emoji 兜底
  - **状态色克制**：正常/中性态回灰色，彩色只留给「值得注意」处；卡片/浮层「1px 半透明描边 + 顶部高光」精致质感
- 扩展指引：新组件请直接引用令牌(如 padding:var(--space-4))，不要再写魔法数字

### ⌨️ v1.9 交互效率飞轮
- **命令面板**：Ctrl+P 一个入口直达一切——输入搜任务、# 搜标签、@ 搜笔记、空输入浏览命令；回车执行，无结果时直接创建任务
- **键盘操作**：Ctrl+N 快速捕获 · J/K 选任务 · Space/D 勾选 · S 顺延 · 1/2/3 定优先级 · Delete 删除 · Ctrl+Z 撤销 · ? 全部快捷键
- **自然语言快捕**：顶栏 ➕ 或 Ctrl+N，打一句「明天上午 45分钟 复习 #agent」回车即入列（时间/时段/耗时/优先级/标签自动识别）
- **批量与撤销**：「☑ 批量模式」单击选行 → 底部全选/反选/完成/顺延/删除/设优先级；所有操作可 Ctrl+Z 撤销（服务端 operations_log 快照回滚）
- **悬停动作**：任务行悬停出 ✓/⏭/✏️，复习卡悬停出 [1-5] 质量评分条（窄屏自动隐藏）

### 🧭 v1.8s 智能导航（阶段二）
- **排期建议**：洞察面板「⏱ 本周时间预算」内点「🔮 下一个任务排哪天?」——综合专注时段+未来三日负荷+薄弱领域给出落点与置信度；专注时段未解锁时自动降级
- **叙事周报**：洞察面板底部「📋 本周叙事周报」折叠展开即生成(人话总结/亮点/风险预警/下周建议)，可一键复制 Markdown
- **今日焦点**：顶栏一句话告诉你现在最该做什么(五级优先判定)，5 分钟自刷新，点 ✕ 当天隐藏

### 🏷️ v1.8 数据质量工具
- **标签批量补录**：python tag_notes.py --dry-run 预览推荐 → python tag_notes.py --yes 写入。推荐词库在 tag_keywords.json 可直接编辑；已有 tags 行的笔记永不覆盖
- **quality 加权规则**：R_有效 = R × 质量系数({5:1.0,4:0.9,3:0.7,2:0.5,1:0.3,0:0.1} 近期优先衰减加权)；未复习过的概念不受影响
