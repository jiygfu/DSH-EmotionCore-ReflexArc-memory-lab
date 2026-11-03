@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo === SoulCore 日常整理 ===
"%PY%" -m soulcore daily --sync-limit 500 --appraise-limit 30 --budget 12
echo.
echo 完成。未生成日记、未注入发言层、未写 SurfCore。
pause
