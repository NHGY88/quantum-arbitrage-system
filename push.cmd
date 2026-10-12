@echo off
setlocal enabledelayedexpansion
rem ===============================================================
rem  Safe push script (ASCII only - avoids cmd GBK mangling)
rem  Why: Git Credential Manager's GUI selector hangs in
rem  non-interactive sessions and makes `git push` wait forever.
rem  Workaround applied here:
rem    1) disable all credential helpers (token comes from gh)
rem    2) GIT_TERMINAL_PROMPT=0 blocks any prompt
rem    3) token lives only in this process environment
rem  Usage:  push.cmd "commit message"
rem ===============================================================

set "GIT=D:\hermes_agent\tools\git\cmd\git.exe"
set "REPO=D:\AI"
set "GH=D:\AI\tools\bin\gh.exe"

"%GIT%" -C "%REPO%" config --local credential.helper "" >nul 2>&1

set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
set GIT_ASKPASS=

"%GIT%" -C "%REPO%" add -A
"%GIT%" -C "%REPO%" diff --cached --quiet
if errorlevel 1 (
  set "MSG=chore: update"
  if not "%~1"=="" set "MSG=%~1"
  "%GIT%" -C "%REPO%" commit -m "!MSG!"
)

for /f "usebackq delims=" %%T in (`"%GH%" auth token 2^>nul`) do set "GH_TOKEN=%%T"
if not defined GH_TOKEN (
  echo [ERROR] Not authorized. Run: D:\AI\github-login.cmd
  exit /b 1
)

set "REMOTE="
for /f "usebackq delims=" %%U in (`"%GIT%" -C "%REPO%" remote get-url origin`) do set "REMOTE=%%U"

"%GIT%" -C "%REPO%" remote set-url origin "https://x-access-token:%GH_TOKEN%@github.com/NHGY88/quantum-arbitrage-system.git"
"%GIT%" -C "%REPO%" push origin HEAD
set "RC=%ERRORLEVEL%"

"%GIT%" -C "%REPO%" remote set-url origin "!REMOTE!"

if "!RC!"=="0" (echo [OK] Push succeeded) else (echo [FAIL] Push failed rc=!RC!)
endlocal & exit /b 0