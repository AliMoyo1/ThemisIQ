@echo off
title One For All — Unified Compliance Platform
echo ============================================
echo   One For All — Unified Compliance Platform
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
if not exist ".deps_installed" (
    echo Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo. > .deps_installed
    echo Dependencies installed successfully.
    echo.
)

:: Copy .env if not present
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo Created .env from .env.example — edit it with your settings.
        echo.
    )
)

:: Create data directory
if not exist "data" mkdir data

echo Starting server on http://localhost:8000
echo.
echo Default credentials:
echo   Admin:      admin / Admin@123!
echo   Compliance: compliance / Comply@123!
echo   DPO:        dpo / Privacy@123!
echo   BCM:        bcm / Bcm@123!
echo.
echo Press Ctrl+C to stop the server.
echo ============================================
echo.

python main.py
pause
