@echo off
chcp 65001 > nul
setlocal EnableExtensions

REM === PHASE 0: 行動規範の固定 ===
REM プロジェクトルートに移動し、カレントディレクトリを固定する
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

REM === ディレクトリ準備 ===
if not exist "logs" mkdir "logs"
if not exist "data" mkdir "data"

REM === ログファイル名 ===
set "TIMESTAMP=%date:/=%_%time::=%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "LOG_FILE=%PROJECT_ROOT%\logs\boot_%TIMESTAMP%.log"

echo.
echo ===================================================
echo   NIA SYSTEM LAUNCHER (COMPLETE)
echo   Phase 1: Entry Point Unified
echo   ROOT: %PROJECT_ROOT%
echo   LOG : %LOG_FILE%
echo ===================================================
echo.

REM === Python環境確認 ===
set "VENV_ACTIVATE=.venv\Scripts\activate.bat"
if not exist "%VENV_ACTIVATE%" (
    echo [ERROR] Virtual Environment not found at .venv
    echo Please run 'setup_env.bat' or create venv first.
    pause
    exit /b 1
)

REM === Backend起動 (メインウィンドウ) ===
echo [LAUNCH] Starting Backend (Main Window)...
echo [INFO]  Logging to stdout and %LOG_FILE% (Simulated)
echo.

call "%VENV_ACTIVATE%"
set PYTHONPATH=.

REM バックグラウンドでサーバー起動
start "NIA Backend" cmd /k "cd /d %PROJECT_ROOT% && set PYTHONPATH=. && .venv\Scripts\python.exe -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload"

REM === Backendの起動待機 (Health Check) ===
echo [WAIT] Waiting for backend to be healthy...
powershell -Command "for($i=0;$i -lt 30;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health | Out-Null; exit 0}catch{Start-Sleep -Seconds 1}}; exit 1"

if errorlevel 1 (
    echo [ERROR] Backend failed to start or is not reachable.
    echo Please check the backend console window for errors.
    pause
    exit /b 1
)
echo [OK] Backend is UP!

REM === Nero Server起動 (別ウィンドウ) ===
set "NERO_ROOT=C:\Users\jk023\Desktop\Nero"
if exist "%NERO_ROOT%\nero\server.py" (
    REM ポート8001を使っている既存プロセスを終了
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
        echo [CLEANUP] Killing old process on port 8001 (PID=%%p)
        taskkill /F /PID %%p >nul 2>&1
    )
    echo [LAUNCH] Starting Nero Server...
    start "Nero Server" cmd /k "cd /d %NERO_ROOT% && .venv\Scripts\python.exe -m uvicorn nero.server:app --host 127.0.0.1 --port 8001 --reload"
) else (
    echo [SKIP] Nero not found at %NERO_ROOT%
)

REM === Frontend起動 (別ウィンドウ) ===
echo [LAUNCH] Starting Frontend...
if exist "frontend" (
    start "Nia Frontend" cmd /k "cd /d %PROJECT_ROOT%\frontend && npm run dev"

    REM ブラウザ自動起動
    timeout /t 3 > nul
    start http://localhost:3000
) else (
    echo [WARN] Frontend directory not found via batch. Check config.
)

echo.
echo [DONE] NIA System Launched.
pause
