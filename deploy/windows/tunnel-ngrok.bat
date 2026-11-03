@echo off
REM ============================================================
REM  Publish ZhiYuan Study with ngrok free fixed domain
REM  Zero cost, no credit card. Needs a free ngrok account (email only).
REM  Get authtoken: https://dashboard.ngrok.com/get-started/your-authtoken
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === ngrok free fixed domain ===
echo     First run: it will ask for your authtoken (free signup, email only).
echo     Free plan limits: 1 GB/month, 20k requests, one interstitial page.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-ngrok.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo [X] Exited with code %RC%. See messages above.
pause
exit /b %RC%
