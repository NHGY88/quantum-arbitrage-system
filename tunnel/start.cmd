@echo off
chcp 65001 >nul
start "" /b "D:\hermes_agent\hermes-agent\.venv\Scripts\pythonw.exe" -X utf8 "D:\AI\tunnel\watchdog.py"
exit /b 0