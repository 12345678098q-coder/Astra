@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "ASTRA_PYTHON=runtime\python.exe"
if not exist "%ASTRA_PYTHON%" set "ASTRA_PYTHON=.venv\Scripts\python.exe"
if not exist "%ASTRA_PYTHON%" (
  echo Python runtime not found. Install this fix into the existing Astra folder.
  pause
  exit /b 1
)
"%ASTRA_PYTHON%" -B diagnose_compatibility.py
echo Logs: %LOCALAPPDATA%\Astra\logs
pause
