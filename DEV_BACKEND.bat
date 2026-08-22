@echo off
REM =====================================================================
REM  Backend with AUTO-RELOAD, for when you are editing backend code.
REM
REM  Use this INSTEAD of the backend window that START.bat opens.
REM  Code changes restart the server automatically.
REM
REM  To stop it: press Ctrl+C in this window, then close the window.
REM  (STOP.bat cannot always stop a reload server -- see scripts\_backend.bat)
REM =====================================================================
title Fire DEX - Backend DEV (auto-reload)
color 0B
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    color 0C
    echo.
    echo   [X] Backend is not set up yet. Run START.bat once first.
    echo.
    pause
    exit /b 1
)

echo.
echo   FIRE DEX - BACKEND (development, auto-reload ON)
echo   http://127.0.0.1:8000       docs: http://127.0.0.1:8000/docs
echo   Press Ctrl+C to stop.
echo   ------------------------------------------------------------
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

echo.
echo   Backend stopped.
pause
