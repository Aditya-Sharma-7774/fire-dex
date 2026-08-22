@echo off
title Fire DEX - Stop
cd /d "%~dp0"
color 0C

echo.
echo   ===================================================
echo      STOPPING FIRE DEX
echo   ===================================================
echo.

call "%~dp0scripts\_stop_ports.bat"

echo.
echo   Done. Backend and frontend are stopped.
echo   You can close the two server windows if they are still open.
echo.
pause
