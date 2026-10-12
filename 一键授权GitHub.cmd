@echo off
chcp 65001 >nul
title GitHub 一键授权（只需一次）
echo ============================================
echo   第 1 步：你会看到一个浏览器页面
echo   第 2 步：在页面上点 "Authorize GitHub"
echo   第 3 步：回到这里按任意键结束
echo.
echo   全程只需要你点一下鼠标，不用敲命令。
echo ============================================
echo.

"D:\AI\tools\bin\gh.exe" auth login --hostname github.com --git-protocol https --web

echo.
echo ============================================
echo   授权完成后，按任意键关闭
echo ============================================
pause >nul