@echo off
chcp 65001 >nul
title GitHub 一键授权
echo 正在启动浏览器授权，请在页面点 Authorize GitHub。
echo 完成后本窗口会提示，按任意键关闭。
echo.
"D:\AI\tools\bin\gh.exe" auth login --hostname github.com --git-protocol https --web
echo.
echo 授权完成，按任意键关闭。
pause >nul