@echo off
chcp 65001 >nul
set PYTHONUTF8=1
python "%~dp0th.py" run
if errorlevel 1 pause
