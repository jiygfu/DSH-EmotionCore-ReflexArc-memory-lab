@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo === SoulCore 睡前整理 ===
"%PY%" -m soulcore sleep --budget 12
echo.
echo 完成。现在可以关闭 DSH。
pause
