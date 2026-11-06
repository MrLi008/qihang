@echo off
setlocal
rem 契衡 GUI 免安装入口：gui.cmd [--self-check]
rem 可选：set QIHANG_PYTHON=<python.exe 路径> 指定解释器；默认用 PATH 里的 python

set "PY=%QIHANG_PYTHON%"
if not defined PY set "PY=python"

"%PY%" "%~dp0run.py" --gui %*
if errorlevel 1 (
    echo.
    pause
)
exit /b %ERRORLEVEL%
