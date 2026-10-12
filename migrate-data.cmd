@echo off
rem Completes the C->D migration of the opencode data dir (sessions/db/logs).
rem Run this AFTER closing the OpenCode app. Re-run is safe/idempotent.
setlocal
chcp 65001 >nul
set SRC=C:\Users\pc\.local\share\opencode
set DST=D:\AI\.local\share\opencode
set BAK=C:\Users\pc\.local\share\opencode.__mig

if not exist "%DST%" mkdir "%DST%"
echo [1/4] copying to D drive ...
robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /R:1 /W:1 >nul
echo [2/4] swapping C dir for a junction ...
if exist "%BAK%" rmdir /S /Q "%BAK%"
move "%SRC%" "%BAK%" >nul
if errorlevel 1 (
  echo FAILED: cannot move %SRC% - close OpenCode first.
  pause
  exit /b 1
)
mklink /J "%SRC%" "%DST%" >nul
echo [3/4] verifying ...
if not exist "%SRC%\opencode.db" (
  echo WARNING: junction target looks wrong, rolling back.
  rmdir "%SRC%"
  move "%BAK%" "%SRC%" >nul
  pause
  exit /b 1
)
echo [4/4] done. Removing old copy from C ...
rmdir /S /Q "%BAK%"
echo.
echo DONE. opencode data now lives on D:\AI\.local\share\opencode
echo C: %SRC% is a junction pointing there.
pause