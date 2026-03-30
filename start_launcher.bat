@echo off
setlocal enabledelayedexpansion
cd /d %~dp0

echo ===================================
echo     StreamNotify Launcher Boot
echo ===================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in your PATH.
    echo Please install Python 3.10+ to use StreamNotify.
    pause
    exit /b 1
)

:: Find an available python executable (either root venv, or system python to spin up the launcher)
set PYTHON_CMD=pythonw
if exist ".venv\Scripts\pythonw.exe" (
    set PYTHON_CMD=".venv\Scripts\pythonw.exe"
) else if exist "venv\Scripts\pythonw.exe" (
    set PYTHON_CMD="venv\Scripts\pythonw.exe"
)

:: Start the Python launcher GUI using the found python
echo [INFO] Starting StreamNotify Launcher...
start "" %PYTHON_CMD% launcher.py
exit
