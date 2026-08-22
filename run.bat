@echo off
REM =====================================================================
REM  Fire DEX - start backend and frontend together
REM  Opens two terminal windows. Close them to stop the servers.
REM =====================================================================

setlocal
cd /d "%~dp0"

echo.
echo   FIRE DEX
echo   Agentic AI-Powered Multi-Chain Smart Wallet
echo   -------------------------------------------
echo.

REM --- checks ---------------------------------------------------------
if not exist "backend\.venv\Scripts\python.exe" (
    echo  [X] Backend virtual environment not found.
    echo.
    echo      Run these first:
    echo        cd backend
    echo        python -m venv .venv
    echo        .venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo  [X] Frontend dependencies not installed.
    echo.
    echo      Run these first:
    echo        cd frontend
    echo        npm install
    echo.
    pause
    exit /b 1
)

if not exist "backend\.env" (
    echo  [i] backend\.env missing - creating it from .env.example
    copy /y "backend\.env.example" "backend\.env" >nul
)

if not exist "frontend\.env" (
    echo  [i] frontend\.env missing - creating it from .env.example
    copy /y "frontend\.env.example" "frontend\.env" >nul
)

REM --- launch ---------------------------------------------------------
echo  [1/2] Starting backend  ...  http://127.0.0.1:8000
start "Fire DEX - Backend" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python -m uvicorn app.main:app --reload"

echo  [2/2] Starting frontend ...  http://localhost:5173
start "Fire DEX - Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo   Both servers are starting in separate windows.
echo.
echo     UI       http://localhost:5173
echo     API      http://127.0.0.1:8000
echo     API docs http://127.0.0.1:8000/docs
echo.
echo   Close those two windows to stop the servers.
echo.
pause
