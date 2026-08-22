@echo off
REM Started by START.bat -- do not run this directly.
title Fire DEX - Backend (port 8000)
color 0B
cd /d "%~dp0..\backend"

echo.
echo   FIRE DEX - BACKEND
echo   http://127.0.0.1:8000       docs: http://127.0.0.1:8000/docs
echo   Close this window to stop the backend.
echo   ------------------------------------------------------------
echo.

REM NOTE: --reload is deliberately NOT used here.
REM
REM With --reload, uvicorn runs a supervisor process that hands an
REM inherited socket to a worker child. If the supervisor is stopped, the
REM worker keeps serving on the same port, and Windows still reports the
REM port as owned by the dead supervisor -- so the server cannot be shut
REM down cleanly. Running a single process keeps STOP.bat reliable.
REM
REM While actively editing backend code, use DEV_BACKEND.bat instead,
REM which does enable auto-reload.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo   Backend stopped.
pause
