@echo off
setlocal
rem 契衡 CLI 免安装入口：run.cmd run --scenario a4
rem 可选：set QIHANG_PYTHON=<python.exe 路径> 指定解释器；默认用 PATH 里的 python

set "PY=%QIHANG_PYTHON%"
if not defined PY set "PY=python"

if "%~1"=="" (
    "%PY%" "%~dp0run.py"
    echo.
    pause
    exit /b 2
)

"%PY%" "%~dp0run.py" %*
exit /b %ERRORLEVEL%
