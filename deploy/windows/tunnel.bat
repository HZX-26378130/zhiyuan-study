@echo off
REM ============================================================
REM  Publish ZhiYuan Study to the internet via Cloudflare Tunnel
REM  Free, no registration, no credit card required.
REM  Close this window to stop the public access.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Starting local server + Cloudflare tunnel ===
echo     First run will download cloudflared (~40 MB).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo [X] Tunnel exited with code %RC%. See messages above.
pause
exit /b %RC%
