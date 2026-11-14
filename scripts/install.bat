@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r build-support\requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade --no-deps --target ".venv\qt-legacy" PySide6_Essentials==6.6.3.1 shiboken6==6.6.3.1
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -u -m processes.astap_updates
if errorlevel 1 (
    echo ASTAP installation failed. Astra will retry on startup.
    exit /b 1
)
echo Astra and ASTAP are ready. Run Astra.exe.
