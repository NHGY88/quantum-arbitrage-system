@echo off
chcp 65001 >nul
cd /d D:\AI\server
start "" /b "D:\hermes_agent\hermes-agent\.venv\Scripts\python.exe" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
exit /b 0