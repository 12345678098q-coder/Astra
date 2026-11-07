@echo off
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" -B app.py
) else if exist "..\runtime\python.exe" (
  "..\runtime\python.exe" -B app.py
) else (
  python -B app.py
)
if errorlevel 1 pause
