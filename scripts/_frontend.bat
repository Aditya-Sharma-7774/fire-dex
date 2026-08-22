@echo off
REM Started by START.bat -- do not run this directly.
title Fire DEX - Frontend (port 5173)
color 0D
cd /d "%~dp0..\frontend"

echo.
echo   FIRE DEX - FRONTEND
echo   http://localhost:5173
echo   Close this window to stop the frontend.
echo   ------------------------------------------------------------
echo.

call npm run dev

echo.
echo   Frontend stopped.
pause
