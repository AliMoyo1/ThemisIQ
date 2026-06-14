@echo off
title DPIAforge
color 1F
cls

echo.
echo  ██████╗ ██████╗ ██╗ █████╗ ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
echo  ██╔══██╗██╔══██╗██║██╔══██╗██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
echo  ██║  ██║██████╔╝██║███████║█████╗  ██║   ██║██████╔╝██║  ███╗█████╗
echo  ██║  ██║██╔═══╝ ██║██╔══██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
echo  ██████╔╝██║     ██║██║  ██║██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
echo  ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
echo.
echo                           by ALI MOYO
echo  ─────────────────────────────────────────────────────────────────────────
echo.

:: Check if .env exists
if not exist ".env" (
    echo  [WARNING] No .env file found!
    echo  Copying .env.example to .env ...
    copy ".env.example" ".env" >nul 2>&1
    echo.
    echo  Please edit .env and add your API key, then re-run this file.
    echo.
    pause
    start notepad ".env"
    exit /b
)

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python not found. Please install Python from https://python.org
        echo.
        pause
        exit /b
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

:: Check Flask is installed
%PYTHON% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo  [SETUP] Installing dependencies...
    echo.
    %PYTHON% -m pip install flask python-docx python-dotenv requests
    echo.
)

:: Open browser after 2 seconds
echo  Starting DPIAforge at http://localhost:5000
echo.
start "" timeout /t 2 >nul
start "" "http://localhost:5000"

echo  ─────────────────────────────────────────────────────────────────────────
echo  DPIAforge is running. Press Ctrl+C to stop.
echo  ─────────────────────────────────────────────────────────────────────────
echo.

%PYTHON% app.py

echo.
echo  DPIAforge has stopped.
pause
