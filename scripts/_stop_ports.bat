@echo off
REM Stops the Fire DEX servers.
REM Called by START.bat (with "quiet") and by STOP.bat.
REM
REM Two stages, deliberately in this order:
REM   1. close our own windows by title -- targeted, so a server belonging
REM      to some other project is never killed by accident
REM   2. free ports 8000/5173 if anything is still holding them, e.g. a
REM      uvicorn --reload worker whose supervisor window was closed
setlocal

set "QUIET=%~1"

REM --- stage 1: our own windows -------------------------------------
taskkill /f /t /fi "WINDOWTITLE eq Fire DEX - Backend*"  >nul 2>&1
taskkill /f /t /fi "WINDOWTITLE eq Fire DEX - Frontend*" >nul 2>&1

REM --- stage 2: anything still on the ports --------------------------
REM PowerShell is used here because parsing netstat output in batch is
REM fragile; Get-NetTCPConnection gives the owning PID directly.
for %%P in (8000 5173) do (
    powershell -NoProfile -Command ^
      "Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $pid_ = $_.OwningProcess; Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue; Write-Host ('        Stopped process on port %%P (PID ' + $pid_ + ')') }"
)

if "%QUIET%"=="quiet" echo         Ports 8000 and 5173 are free.

endlocal
exit /b 0
