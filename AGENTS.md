# AGENTS.md · 项目长期规则

> 本文件是 workspace 级指令文件（ZCode 自动加载）。对本项目工作的所有 AI 会话生效。
> 与本文件冲突的临时指令，须先确认用户明确意图，再谨慎执行。

---

## 1. 当前项目状态

- 项目：本地学习管理应用（Python 后端 + HTML/JS/CSS 显示层，`dashboard.html` / `editor.html`，模板在 `templates/`）。
- 阶段：**第一轮工程治理已全部完成并锁定**，当前处于 **Phase 2 — Professional UI/UX + Product Experience**。
- 第一轮治理成果（基线，不得回退）：
  - P1 技术债务全部清零
  - 业务测试 **43 套 / 472 例 / 0 失败**（入口：`run_tests.py`；含 icon_contract_test 8 例匹配型图标契约）
  - 视觉回归 **18 / 18 PASS**（2 页面 × 3 主题 × 3 视口，见 `VISUAL_REGRESSION.md`）
  - 三主题（Theme Architecture）稳定
  - 架构拆分、路由治理、CSS 权重治理、CSS 外链化、历史归档清理、测试产物分离均已完成
- Git 工作区必须保持 clean 起步、clean 收尾（见第 10 节）。

## 2. Phase 2 工作目标

目标：在不触碰第一轮成果的前提下，把产品从"功能可用"提升到"专业产品体验"。

- 视觉方向：**Professional / Modern / Clean**
- 体验方向：**High information density、Long-session usability、Product-oriented**
- 手段：显示层（HTML/CSS/JS 交互层）的迭代优化，而非架构或逻辑改动。

## 3. UI/UX 优先级

按序取舍，冲突时高层优先：

1. **清晰的信息层级** — 用户 1 秒内能定位主要信息与主要操作
2. **Typography consistency** — 字号/字重/行高成体系，禁止随手新增字号
3. **Stable spacing** — 间距来自有限刻度集合，禁止魔法数字
4. **Predictable interaction** — 同类控件行为一致，无惊喜
5. **Clear feedback** — 每个操作有明确、克制的状态反馈
6. **High information density** — 服务长时间使用，避免大面积留白空洞
7. **Long-term usability** — 长会话不疲劳、不闪动、不跳动

## 4. 产品体验优先级

- 以"用户每天反复使用的学习工具"标准衡量，不以"演示效果"衡量。
- 稳定 > 炫技；可预期 > 惊喜；信息密度 > 视觉表演。
- 任何新交互必须先回答：用户在什么场景下需要它？删除它有什么损失？
- 动效只用于传达状态变化（如确认、过渡），且须短促、可关闭、不引起布局跳动。

## 5. 三主题保护规则

- 主题系统位于 `theme.py` 及其对应 CSS 变量层，**禁止修改 Theme Architecture 本身**。
- 三主题（当前稳定的三套配色/模式）必须始终同时可用、同时通过测试。
- 新增/修改任何样式必须使用现有 CSS 变量 / design token；**禁止硬编码颜色、字号、间距**。
- 每次涉及样式的改动，三主题逐一切换人工检查一遍，并跑视觉回归。

## 6. UI 改造边界

允许：
- `templates/`、`dashboard.html`、`editor.html` 内的模板结构与类名
- 外链化的 CSS 文件（选择器、布局、间距、排版）
- 纯展示层的 JS（交互反馈、状态提示、焦点管理）

不允许：
- 修改业务逻辑、API 行为、数据结构（`*_test.py` 覆盖的后端模块）
- 修改路由治理结果与路由契约
- 修改 CSS 架构分层（外链化结构、权重治理结果）
- 修改视觉回归 baseline（`visual_regression/` 内 PNG 与脚本）
- 修改测试产物分离结构（`tests_output/` 等产物目录）
- 大规模架构重构、技术栈更换、依赖新增

## 7. 禁止 AI 风格 UI 的规则

以下模式一律禁止，评审时视为不合格：

- Emoji 作为正式功能图标（须使用专业 Icon System / 矢量图标）
- 大面积或多处渐变
- 玻璃拟态（glassmorphism）、毛玻璃叠加
- Glow / Neon 发光效果
- 彩色阴影（阴影只允许中性色、低透明度）
- 过度圆角（圆角须克制、成体系）
- 把所有区域都包成 Card（卡片泛滥）
- 无意义动画、装饰性动效
- AI 科技感装饰（网格线、光斑、粒子、伪 3D 等）
- Generic AI SaaS aesthetics（千篇一律的模板感落地页风）
- Dribbble concept style（只求截图好看、不可用的概念稿风格）

对应地，必须优先：
清晰的信息层级、专业 Icon System、Typography consistency、Stable spacing、
Predictable interaction、Clear feedback、High information density、Long-term usability。

## 8. 任务执行规则

任何 UI/UX Task 必须按以下流程执行，不得跳步：

```
先理解 → 明确问题 → 提出计划 → 最小范围修改 → 测试
→ 检查三主题 → 视觉回归 → Git 检查 → 汇报 → 停止
```

- **先理解**：改动前先读懂相关模板/CSS/测试的现状。
- **明确问题**：用一句话说清要解决的具体问题，不解决问题清单以外的事。
- **提出计划**：动手前先给出改动范围与验收标准，等确认后再改。
- **最小范围修改**：只动与问题直接相关的文件与选择器。
- **禁止顺手修改无关模块**：发现相邻问题记录到 BACKLOG/汇报中，不当场改。
- **汇报后停止**：汇报结果并结束本轮，不自行开启下一项任务。

## 9. 测试与视觉回归规则

- 任何涉及模板、CSS、交互的改动后必须依次执行：
  1. 业务测试：`python run_tests.py`（43 套 / 472 例，0 失败为门禁；建议用带 tkinter 的完整 Python 发行版，见 README「环境差异说明」）
  2. 三主题切换人工检查（每主题核心页面过一遍）
  3. 视觉回归：`python visual_regression\run_visual_tests.py`（18/18 PASS 为门禁；需 playwright + Pillow 环境）
- 任一门禁失败即视为改动不成立：先定位原因，禁止通过改测试、改 baseline、跳过用例来"变绿"。
- 若 UI 改动是有意为之且需更新 baseline，须在计划中显式提出、经确认后按 `VISUAL_REGRESSION.md` 流程更新，并说明理由。

### 9.1 Baseline 更新纪律（R-2 反模式防线，2026-08-31 增）

视觉回归 FAIL 时，**禁止**以「更新 baseline → 变绿」作为处置。强制顺序：

```
FAIL → 人工核对 diff 图（visual_regression/diff/）→ 归因三选一：
  (a) 预期内变更（有意 UI 改动）→ 修复缺陷后（若有）→ 显式 --update-baseline + commit 记录理由
  (b) 确定性环境变更 → 修复环境，禁止更新 baseline
  (c) 真回归 → 修复代码，复测 PASS
```

- 三主题 diff 数值高度一致 + 稳定性 0.000% ⇒ 结构性变更，必须逐项归因，不得合并表述为"数据方差"。
- 任何 baseline 更新的 commit message 必须写明：失败组合、diff 归因类别、人工核对凭据（diff 图路径）。

## 10. Git 工作区保护规则

- 开始任何任务前：`git status` 必须为 clean；不 clean 先向用户汇报，不得在其上叠加改动。
- 提交粒度：一个任务一次提交，提交信息描述本次 UI/UX 改动与验收结果。
- 禁止提交：测试运行产生的临时产物、截图输出、日志（`app.log`）、`__pycache__` 等非源码文件。
- 禁止操作：`git push --force`、`git reset --hard` 丢弃他人/历史改动、直接改写已推送历史。
- 任务收尾前再次 `git status` / `git diff`，确认改动范围与计划一致后提交并汇报。

## 11. 验收证据完整性（R-3b 防线，2026-08-31 增）

- commit message / 报告中的每条验收声明，必须可核验：**附测试函数名或文件路径**。
  禁止「XX 控件断言已覆盖」这类不落到具体测试函数的概括表述。
- 禁止声明不存在的测试。写入验收前逐条自问：该断言在哪个文件的哪个函数？
- 数量下限断言（`count(x) >= N`）不构成覆盖证明；契约必须是**匹配型**（A 存在 ⇒ B 必须存在）。
- 发现历史验收声明失实：**不改写历史**，以独立修正记录（`refactor_phase2/` 编号文档）澄清，并补齐缺失的测试。

## 12. 单写入方协议（Task 01 并发审计产出，2026-08-31 增）

背景：2026-08-31 08:08–08:23 曾观测到审查窗口内文件被并行会话修改（Task06 批次）。
Task 01 三次指纹审计（482 文件，21m24s+50min 零差异）后判定 READY。规程：

- **草稿/脚本/探针/报告**一律写 `%TEMP%`（仓库外）；仓库内只留正式治理记录。
- **验证窗口**：开启时记录 T0 + 全仓库 SHA-256 指纹（存仓库外）；关闭时同参数指纹比对，
  差异逐项归因（(a) 已知工具按设计写入 / (b) 外部未归因写入 / (c) 无法判定）后才允许提交。
- **双证据收尾**：`git status --porcelain` 与 T0 逐行一致 **且** 指纹 diff 中除本任务改动外为零。
- 出现 (b) 类写入 ⇒ 立即停止写入类操作，归因治理后方可继续（READY → NOT READY 翻转）。
- 取证/审计类任务禁止运行会写仓库的套件（`run_tests.py`、视觉回归），防止自造信号。
- **仓库备份（2026-08-31 事件教训）**：本仓库历史曾于 09:50 被外部进程清空并重建
  （见 `refactor_phase2/47`）。此后必须维持异地备份：远端仓库或每周 `git bundle --all`；
  并发会话期间禁用 `git stash`（半完成状态会同时污染工作树与对象库）。

## 13. 已知覆盖盲区与治理记录

- `.ni` 矢量图标契约：`icon_contract_test.py`（匹配型，逐元素），来源见 `refactor_phase2/44`。
- Task06 验收声明与 VR 归因修正记录：`refactor_phase2/44_task06_acceptance_correction.md`。
- Task 01 并发审计报告归档：`refactor_phase2/45_task01_concurrency_audit.md`。

## 14. UI 冻结（2026-09-01 起生效）

**冻结基准**：tag `ui-freeze-2026-09-01`
（UI 代码在 `17c1ad2` 定稿，终审与实施记录在 `20c750f`，本冻结规则随之入库）。

**依据**：Phase UI-E Stage 1 只读终审（指纹 `T_UE1_0`，真实服务 E2E 走查 × 3 主题）
结论 **READY FOR UI FREEZE**；其前置条件（<10 行内容卫生批次）已于 `17c1ad2` 落地。
完整审计与实施记录：`refactor_phase2/54_ui_e_final_audit_and_content_hygiene_report.md`。

**冻结范围（不可变契约）**——以下六项为**信息架构与设计方向**层面的定案：

1. 四段式 `section` 架构：今天 / 记忆与复习 / 进度与洞察 / 知识与资源
2. Review（行动队列）↔ Decay（保持率全景）的职责拆分——不再并排重复罗列同一批概念
3. Quiet Intelligence 视觉语言：design token、10px 扁平卡片、统一字阶、无渐变
4. 三主题机制与 17 个主题变量契约（另见 §5）
5. Today 信息序：`today → tasks → overview`（焦点 → 当前任务 → 支撑进度）
6. 概念名显示层归一（`render_data._clabel`）——原始解析 token 不进 UI

**例外流程**：确需改动上述任一项时，必须
① 书面说明产品理由（不得仅凭审美偏好）；
② 评估对主题变量契约、6 个契约测试套件、18 组 VR baseline 的影响；
③ 走 §9.1 baseline 纪律（FAIL → 人工核 diff → 三分类归因 → 修复后才更新）；
④ 单独 commit，message 前缀标注 `[FREEZE EXCEPTION]`。

**冻结 ≠ 停止修复**：缺陷类修复（无障碍、对比度、焦点可达性、数据流/渲染错误、
文案与拼写）照常进行，不受本条约束。本条约束的是**设计方向与信息架构的再次改版**。
