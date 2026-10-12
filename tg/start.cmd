@echo off
chcp 65001 >nul
set PYTHONUTF8=1
start "" /b "D:\hermes_agent\hermes-agent\.venv\Scripts\pythonw.exe" -X utf8 "D:\AI\tg\watchdog.py"
exit /b 0
