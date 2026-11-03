@echo off
REM ============================================================
REM  Bind ZhiYuan Study to your own domain (Cloudflare named tunnel)
REM  Free, no credit card. Run this ONCE.
REM  After that, use tunnel-fixed.bat to start.
REM ============================================================
setlocal
cd /d "%~dp0"

set "DOMAIN="
set /p DOMAIN=Enter your domain (example study.example.com):
if "%DOMAIN%"=="" (
    echo [X] No domain provided. Abort.
    pause
    exit /b 1
)

echo.
echo === Binding https://%DOMAIN% to local service ===
echo     Step 1 will open a browser: log in to Cloudflare and pick your domain.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-domain.ps1" -Domain "%DOMAIN%" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [OK] Domain bound. Next: double-click tunnel-fixed.bat
) else (
    echo [X] Setup failed with exit code %RC%. See messages above.
)
pause
exit /b %RC%
