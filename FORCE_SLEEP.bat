@echo off
chcp 65001 > nul
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

echo.
echo =========================================
echo   NIA FORCE SLEEP (Manual Trigger)
echo   Running sleep_cycle.py...
echo =========================================
echo.

set "VENV_ACTIVATE=.venv\Scripts\activate.bat"
if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
) else (
    echo [ERROR] .venv not found.
    pause
    exit /b 1
)

set PYTHONPATH=.
python backend/scripts/sleep_cycle.py

echo.
echo [DONE] Sleep cycle finished.
pause
