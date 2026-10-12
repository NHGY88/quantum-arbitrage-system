@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
python -X utf8 "%~dp0tg.py" %*
exit /b %ERRORLEVEL%