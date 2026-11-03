@echo off
REM ============================================================
REM  Start ZhiYuan Study on your fixed domain (Cloudflare tunnel)
REM  Requires setup-domain.bat to have been run once.
REM ============================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-fixed.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo [X] Exited with code %RC%. See messages above.
pause
exit /b %RC%
