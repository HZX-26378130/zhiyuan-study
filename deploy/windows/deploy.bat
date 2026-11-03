@echo off
REM ============================================================
REM  ZhiYuan Study - first-time deploy to Oracle VM
REM  Double-click this file. It asks for the VM public IP once,
REM  then caches it in vm-host.txt for the other scripts.
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

REM strip spaces
for /f "tokens=* delims= " %%a in ("%VMHOST%") do set "VMHOST=%%a"
> "vm-host.txt" echo %VMHOST%

echo.
echo === Deploying to %VMHOST% ===
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload-to-vm.ps1" -VmHost %VMHOST% -Install %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [OK] Deploy finished.
    echo      Open http://%VMHOST%:8765  and register an account.
    echo      Do not forget: Oracle Console -^> VCN -^> Security List -^> allow inbound TCP 8765
) else (
    echo [X] Deploy failed with exit code %RC%. See the messages above.
)
pause
exit /b %RC%
