@echo off
title Data Protection Sentinel — by Ali Moyo
color 0B

echo.
echo  ██████╗  █████╗ ████████╗ █████╗     ██████╗ ██████╗  ██████╗ ████████╗███████╗ ██████╗████████╗██╗ ██████╗ ███╗   ██╗
echo  ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗    ██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝██║██╔═══██╗████╗  ██║
echo  ██║  ██║███████║   ██║   ███████║    ██████╔╝██████╔╝██║   ██║   ██║   █████╗  ██║        ██║   ██║██║   ██║██╔██╗ ██║
echo  ██║  ██║██╔══██║   ██║   ██╔══██║    ██╔═══╝ ██╔══██╗██║   ██║   ██║   ██╔══╝  ██║        ██║   ██║██║   ██║██║╚██╗██║
echo  ██████╔╝██║  ██║   ██║   ██║  ██║    ██║     ██║  ██║╚██████╔╝   ██║   ███████╗╚██████╗   ██║   ██║╚██████╔╝██║ ╚████║
echo  ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝    ╚═╝     ╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚══════╝ ╚═════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
echo.
echo                              S E N T I N E L  —  by Ali Moyo
echo  ════════════════════════════════════════════════════════════════════════════════════════════
echo.

REM ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.9+ from https://python.org
    pause
    exit /b 1
)

REM ── Kill any old instances on port 5000 ──────────────────────────────────────
echo  [SETUP] Clearing port 5000 (stopping old instances)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM ── Clear Python cache (ensures fresh code is loaded) ────────────────────────
echo  [SETUP] Clearing Python cache...
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1

REM ── Check .env ───────────────────────────────────────────────────────────────
if not exist ".env" (
    echo.
    echo  [SETUP] No .env file found. Creating one now...
    echo ANTHROPIC_API_KEY=your-key-here> .env
    echo SECRET_KEY=sentinel-secret-change-me>> .env
    echo  [SETUP] Please open .env and add your API key, then re-run START.bat
    echo.
    notepad .env
    pause
    exit /b 0
)

REM ── Add SECRET_KEY to .env if missing ────────────────────────────────────────
findstr /i "SECRET_KEY" .env >nul 2>&1
if errorlevel 1 (
    echo SECRET_KEY=sentinel-secret-key-2024>> .env
)

REM ── Install dependencies ──────────────────────────────────────────────────────
echo  [SETUP] Checking / installing dependencies...
pip install -r requirements.txt --quiet --disable-pip-version-check

echo.
echo  ════════════════════════════════════════════════════════════════════════
echo  [OK] Data Protection Sentinel running at: http://localhost:5000
echo  [OK] Default login: admin / sentinel2024
echo  [OK] Press Ctrl+C in this window to stop the server
echo  ════════════════════════════════════════════════════════════════════════
echo.

REM ── Open browser after server has a moment to start ──────────────────────────
timeout /t 3 /nobreak >nul
start "" "http://localhost:5000"

REM ── Start Flask ───────────────────────────────────────────────────────────────
python app.py

pause
