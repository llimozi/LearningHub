# visual_regression/ 开发者文档

> 项目级使用文档见项目根 `VISUAL_REGRESSION.md`。
> 本目录 README 仅描述实现细节（适合改 capture.py / compare.py 时参考）。

## 文件

| 文件 | 职责 |
|---|---|
| config.py | 唯一配置源：VIEWPORTS / THEMES / PAGES / Ready 条件 / Mask / Threshold |
| capture.py | 内嵌启动测试服务、wait ready、mask、截图、动画冻结 |
| compare.py | Pillow 逐像素 diff + diff 图（变化区红描） |
| run_visual_tests.py | 主入口：3 轮稳定性 + baseline 更新 + 回归对比 |
| baselines/ | 基线（git 跟踪） |
| current/ | 本次截图（gitignore） |
| diff/ | diff 图（gitignore） |
| .backup/ | 数据文件临时备份（gitignore） |

## 服务管理

- `capture.start_server()` 调 `build_dashboard.create_server(PORT0)`，
  端口占用自动 +1 试 6 个 → **不干扰用户正式服务**。
- 服务在子线程跑（daemon），主线程跑截图。
- 测试前 `capture.backup_data_files()` → 测试后 `capture.restore_data_files()`。
- 主题切换：直接改 `settings.json`，下次 render 即生效（无需重启）。

## Ready 条件

每页面按 `config.READY_CONDITIONS[page]` 顺序等待：
`selector`（元素出现，state=attached）/ `networkidle`（请求完成）。
任一不满足则报错。

实测确认（不可猜测）：
- dashboard: `#pnl-tasks .task` 服务端内联；`#inswrap .inscell` 是 fetch 完成标志
- editor: `#ed` 立即存在；`#stat` 是 loadNote fetch 完成标志

## Mask 动态区域

`page.screenshot(mask=[locator1, locator2, ...])` 把元素区域涂灰（pink），
不参与后续 diff。`config.MASK_SELECTORS` 按页面配置：

```python
MASK_SELECTORS = {
    "dashboard": [".clock", "#daily-focus"],  # 时钟+每 5 分钟刷新的面板
    "editor": [],
}
```

## 动画冻结

通过 `context.add_init_script(config.ANIMATION_FREEZE_CSS)` 注入：
```css
* { animation: none !important; transition: none !important; }
```
**不修改生产 CSS 文件**。

## localStorage 隔离

每次 `capture_combo` 新建 `context`，不清旧 localStorage——新 context 全新。
**关键**：禁止跨组合共享 context，避免 localStorage 状态泄漏影响稳定性。

## 测试报告格式

主入口打印格式：
```
[STABLE] dashboard__dark__desktop     max_ratio=0.000%
       r1-vs-r2: changed=0/1024000 (0.000%)
       r1-vs-r3: changed=0/1024000 (0.000%)
       r2-vs-r3: changed=0/1024000 (0.000%)
[PASS] dashboard__dark__desktop       changed=0/1024000 (0.000% <= 1.00%)
```

## 新增组合

编辑 `config.py`：
- `VIEWPORTS` / `THEMES` / `PAGES` 加项即可
- `READY_CONDITIONS` 必须有真实 selector（实测确认）
- `MASK_SELECTORS` 列出动态元素

## 排错 Checklist

| 现象 | 排查 |
|---|---|
| 服务启动超时 | `netstat -ano \| grep :8765`：端口被占？看 build_dashboard.py 错误日志 |
| selector 等待超时 | 改用 playwright 手动测：`page.locator(sel).count()` 是否 > 0 |
| 像素差异大 | 跑 `compare.py r1.png r2.png diff.png`，看 diff 图变化区 |
| 数据污染 | `git status` 看 tasks.json 等是否被改；备份-恢复逻辑看 capture.py |
| timeout 但页面已渲染 | 检查 `POST_READY_DELAY_MS` 是否需要加大 |