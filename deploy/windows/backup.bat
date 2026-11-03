@echo off
REM ============================================================
REM  ZhiYuan Study - backup VM data to local .\backups\
REM  For daily automation see README (schtasks command).
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
echo === Backing up data from %VMHOST% ===
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup-from-vm.ps1" -VmHost %VMHOST% %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (echo [OK] Backup saved to ..\..\backups\) else (echo [X] Backup failed, exit code %RC%.)
pause
exit /b %RC%
