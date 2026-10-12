@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d D:\AI\server
"D:\hermes_agent\hermes-agent\.venv\Scripts\python.exe" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port 8000