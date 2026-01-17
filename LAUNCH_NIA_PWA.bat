@echo off
chcp 65001 > nul
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"

echo.
echo =========================================
echo   NIA SYSTEM LAUNCHER (PWA MODE)
echo   ROOT: %PROJECT_ROOT%
echo   HTTPS: https://zima11.taild5de64.ts.net
echo =========================================
echo.

REM --- Safety Check ---
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual Environment not found!
    echo Checked: "%VENV_PY%"
    pause
    exit /b 1
)

REM --- 1. Start API Server ---
echo [1/4] Starting Backend API...
start "NIA API (Do not close)" cmd /k "cd /d "%PROJECT_ROOT%" && "%VENV_PY%" -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload"

REM --- 2. Wait for API to start ---
timeout /t 5 /nobreak > nul

REM --- 3. Build and Start Frontend (Production Mode) ---
echo [2/4] Building Frontend...
cd /d "%FRONTEND_DIR%"
call npm run build

echo [3/4] Starting Frontend (Production Mode)...
start "NIA FRONTEND PWA (Do not close)" cmd /k "cd /d "%FRONTEND_DIR%" && npm run start"

REM --- 4. Set up Tailscale Serve (HTTPS) ---
echo [4/4] Setting up Tailscale Serve (HTTPS)...
timeout /t 3 /nobreak > nul
tailscale serve --bg 3000 > nul 2>&1

REM --- 5. Open Browser ---
timeout /t 5 /nobreak > nul
echo.
echo =========================================
echo   PWA SYSTEM LAUNCHED!
echo   PC:     http://localhost:3000
echo   Mobile: https://zima11.taild5de64.ts.net
echo =========================================
start https://zima11.taild5de64.ts.net

pause
exit /b 0
