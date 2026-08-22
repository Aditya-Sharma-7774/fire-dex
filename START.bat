@echo off
setlocal EnableDelayedExpansion
title Fire DEX - Launcher
cd /d "%~dp0"

REM =====================================================================
REM  FIRE DEX - ONE CLICK LAUNCHER
REM
REM  Just double-click this file. It will:
REM    1. check Python and Node are installed
REM    2. set everything up the first time (venv, packages, .env files)
REM    3. start the backend and frontend in their own windows
REM    4. open the app in your browser
REM
REM  You never need to type a command.
REM =====================================================================

color 0E
echo.
echo   ===================================================
echo      FIRE DEX
echo      Agentic AI-Powered Multi-Chain Smart Wallet
echo   ===================================================
echo.

REM ---------------------------------------------------------------------
REM  STEP 1  Check Python
REM ---------------------------------------------------------------------
echo   [1/6] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo   [X] Python is not installed, or not on your PATH.
    echo.
    echo       Download Python 3.11 or newer from:
    echo         https://www.python.org/downloads/
    echo.
    echo       IMPORTANT: tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo         Python !PYVER! found.

REM ---------------------------------------------------------------------
REM  STEP 2  Check Node.js
REM ---------------------------------------------------------------------
echo   [2/6] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo   [X] Node.js is not installed, or not on your PATH.
    echo.
    echo       Download the LTS version from:
    echo         https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
echo         Node !NODEVER! found.

REM ---------------------------------------------------------------------
REM  STEP 3  Backend setup (only does work the first time)
REM ---------------------------------------------------------------------
echo   [3/6] Preparing backend...

if not exist "backend\.venv\Scripts\python.exe" (
    echo         First run - creating Python environment. This takes a minute...
    python -m venv "backend\.venv"
    if errorlevel 1 (
        color 0C
        echo.
        echo   [X] Could not create the Python virtual environment.
        pause
        exit /b 1
    )

    echo         Installing backend packages...
    "backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "backend\.venv\Scripts\python.exe" -m pip install --quiet -r "backend\requirements.txt" -r "backend\requirements-dev.txt"
    if errorlevel 1 (
        color 0C
        echo.
        echo   [X] Installing backend packages failed.
        echo       Check your internet connection and run this file again.
        pause
        exit /b 1
    )
    echo         Backend packages installed.
) else (
    echo         Already set up.
)

if not exist "backend\.env" (
    copy /y "backend\.env.example" "backend\.env" >nul
    echo         Created backend\.env from the example file.
)

REM ---------------------------------------------------------------------
REM  STEP 4  Frontend setup (only does work the first time)
REM ---------------------------------------------------------------------
echo   [4/6] Preparing frontend...

if not exist "frontend\node_modules" (
    echo         First run - installing frontend packages. This takes a few minutes...
    pushd "frontend"
    call npm install --silent
    set "NPMFAILED=!errorlevel!"
    popd
    if not "!NPMFAILED!"=="0" (
        color 0C
        echo.
        echo   [X] Installing frontend packages failed.
        echo       Check your internet connection and run this file again.
        pause
        exit /b 1
    )
    echo         Frontend packages installed.
) else (
    echo         Already set up.
)

if not exist "frontend\.env" (
    copy /y "frontend\.env.example" "frontend\.env" >nul
    echo         Created frontend\.env from the example file.
)

REM ---------------------------------------------------------------------
REM  STEP 5  Free the ports if something is already running on them
REM ---------------------------------------------------------------------
echo   [5/6] Checking ports 8000 and 5173...
call "%~dp0scripts\_stop_ports.bat" quiet

REM ---------------------------------------------------------------------
REM  STEP 6  Launch
REM ---------------------------------------------------------------------
echo   [6/6] Starting servers...
start "Fire DEX - Backend" "%~dp0scripts\_backend.bat"
start "Fire DEX - Frontend" "%~dp0scripts\_frontend.bat"

echo.
echo   Waiting for the servers to come up...
REM ping is used instead of timeout because timeout fails when this script
REM is run with redirected input (e.g. from another script or a test).
ping -n 10 127.0.0.1 >nul

start "" "http://localhost:5173"

color 0A
echo.
echo   ===================================================
echo      FIRE DEX IS RUNNING
echo   ===================================================
echo.
echo      App          http://localhost:5173
echo      API          http://127.0.0.1:8000
echo      API docs     http://127.0.0.1:8000/docs
echo.
echo      Two other windows opened - those are the servers.
echo      Leave them open while you use the app.
echo.
echo      To stop everything: double-click STOP.bat
echo   ===================================================
echo.
echo   You can close this window now.
echo.
pause
