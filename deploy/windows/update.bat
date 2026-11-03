@echo off
REM ============================================================
REM  ZhiYuan Study - update code on the VM (keeps data and .env)
REM  Double-click after changing code locally.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VMHOST="
if exist "vm-host.txt" set /p VMHOST=<vm-host.txt
if "%VMHOST%"=="" set /p VMHOST=Enter VM public IP (example 123.45.67.89):
if "%VMHOST%"=="" (
    echo [X] No IP provided. Abort.
    pause
    exit /b 1
)
for /f "tokens=* delims= " %%a in ("%VMHOST%") do set "VMHOST=%%a"
> "vm-host.txt" echo %VMHOST%

echo.
echo === Updating %VMHOST% ===
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload-to-vm.ps1" -VmHost %VMHOST% %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (echo [OK] Updated and restarted.) else (echo [X] Update failed, exit code %RC%.)
pause
exit /b %RC%
