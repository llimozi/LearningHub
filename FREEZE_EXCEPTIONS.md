# FREEZE_EXCEPTIONS.md — UI 冻结例外记录

> 冻结基准：tag `ui-freeze-2026-09-01`（AGENTS.md §14，六项不可变契约）
> 本文件记录冻结 tag 之后、开源副本基线（原仓库 HEAD `93c20d6`）之前的 **UI 冻结例外**。
> 取数方式：原仓库 `git log --oneline ui-freeze-2026-09-01..HEAD` + `git diff --stat` 实测（2026-09-03）。

---

## [FREEZE EXCEPTION] 四线并行学习计划面板（#pnl-plan）

- **变更范围**（实测 `git diff --stat ui-freeze-2026-09-01..HEAD -- _app/`，8 文件 +475/−5）：
  ```
   _app/api.py              |   4 +-
   _app/config.py           |   6 +-
   _app/data.py             |   9 ++
   _app/render_data.py      |  75 ++++++++++-
   _app/render_templates.py |  14 +++
   _app/renderer.py         |   4 +
   _app/server.py           |  46 ++++++-
   _app/services.py         | 322 +++++++++++++++++++++++++++++++++++++++
   8 files changed, 475 insertions(+), 5 deletions(-)
  ```
  其中**四线面板本身**由 commit `d2454dd` 引入（实测 `git show --stat d2454dd`）：
  ```
   _app/config.py          |   6 +-
   _app/data.py            |   9 ++
   _app/render_data.py     |  73 +++++++++++++
   _app/render_templates.py|  14 +++
   _app/renderer.py        |   4 +
   plan.json               |  60 +++++++++++
   四线整合与仪表盘更新方案.md | 105 ++++++
   学习大纲总览.md            | 163 ++++++
   学习总计划_四线并行.md      | 251 ++++++++++
   9 files changed, 684 insertions(+), 1 deletion(-)
  ```
  （其余 7 个 _app 文件改动 +400 行属同一时段 planner 自适应反馈与知识归一化等业务提交，非面板本身。）

- **例外理由**：新增**内容型数据面板**（四线学习计划总览，数据源 `plan.json`），复用既有契约组件（`.card/.subj/.bar` 等）与既有四段 `section` 骨架，**未改版冻结六项契约**：
  1. 四段式 section 架构 —— 保持（面板内嵌既有 section，未新增 section 层级；副本 `renderer.py` 实测四段 section 完好）
  2. Review ↔ Decay 职责拆分 —— 未触碰
  3. Quiet Intelligence 视觉语言 —— 复用既有 token，无新视觉模式
  4. 三主题机制与 17 变量契约 —— 未新增主题变量（实测 config/theme 无变量增减）
  5. Today 信息序 —— 未触碰
  6. 概念名显示层归一 `_clabel` —— 未触碰
  另实测确认：**未触及 `templates/`、`dashboard.html`、`editor.html`**（冻结视觉/信息架构面零改动）。

- **关联 commit**（实测 hash）：`d2454dd1717326732bb3df53abc2c2bc74b6f90d`（`feat(dashboard): integrate four-line learning plan into system (plan.json + #pnl-plan)`，2026-09-01）

- **契约防线验证**：冻结后 6 个契约测试套件（theme 19 / icon 8 / focus 3 / undo 3 / route 28 / html 14 / floating 5）+ 18 组 VR baseline 均保持通过（见 CHANGELOG v1.12 终验与 PHASE0 测试验证）。

> 补充说明：本例外发生于开源准备之前的上游开发期，已在原仓库随 `d2454dd` 合入并全量验证。开源副本以其为基线（HEAD `93c20d6` 快照），副本内后续提交（初始 clean copy / 测试修复 / README 措辞）均未再触碰冻结面。
