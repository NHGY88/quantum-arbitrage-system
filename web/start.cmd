@echo off
chcp 65001 >nul
cd /d D:\AI\web
start "" /b "C:\Program Files\nodejs\node.exe" server.js
exit /b 0