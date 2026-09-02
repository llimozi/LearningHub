@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   学习仪表盘 v0.2 交互模式
echo   关闭本窗口 = 停止服务
echo ============================================
where python >nul 2>nul
if %errorlevel%==0 (
  python build_dashboard.py
) else (
  py build_dashboard.py
)
pause
