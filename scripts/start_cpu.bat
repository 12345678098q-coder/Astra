@echo off
setlocal
cd /d "%~dp0.."
set "ASTRA_COMPATIBILITY=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "ASTRA_PYTHON=runtime\python.exe"
if not exist "%ASTRA_PYTHON%" set "ASTRA_PYTHON=.venv\Scripts\python.exe"
if not exist "%ASTRA_PYTHON%" (
  echo Python runtime not found. Install this fix into the existing Astra folder.
  pause
  exit /b 1
)
if not exist "%LOCALAPPDATA%\Astra\logs" mkdir "%LOCALAPPDATA%\Astra\logs"
"%ASTRA_PYTHON%" -B app.py >> "%LOCALAPPDATA%\Astra\logs\launcher.log" 2>&1
if errorlevel 1 (
  echo Astra failed. Logs: %LOCALAPPDATA%\Astra\logs
  pause
)
