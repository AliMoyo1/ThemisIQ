@echo off

:: Always run from the folder this batch file lives in
cd /d "%~dp0"

chcp 65001 >nul 2>&1
title G.R.I.D AI - Compliance Management System
color 0A

echo.
echo  ===============================================
echo   G.R.I.D AI - Compliance Management System
echo   by Ali Moyo
echo  ===============================================
echo.

:: Check Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo  ERROR: Node.js is not installed.
    echo.
    echo  1. Go to https://nodejs.org
    echo  2. Download the LTS version
    echo  3. Install it, then run this file again
    echo.
    pause
    exit /b 1
)

for /f %%i in ('node --version') do echo  Node.js: %%i

:: Install dependencies if missing
if not exist "node_modules" (
    echo.
    echo  Installing dependencies - please wait...
    call npm install
    echo.
)

:: Read PORT from .env
set PORT=3000
if exist ".env" (
    for /f "tokens=1,2 delims==" %%A in (.env) do (
        if "%%A"=="PORT" set PORT=%%B
    )
)

echo.
echo  -----------------------------------------------
echo   URL:      http://localhost:%PORT%
echo   Login:    admin@auditsphere.local
echo   Password: admin123
echo  -----------------------------------------------
echo.
echo  Server starting - browser opens in 3 seconds.
echo  To stop: close this window or press Ctrl+C
echo.

:: Open browser after 3 seconds
start /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%PORT%"

:: Start server
node src/server.js

echo.
color 0C
echo  Server stopped. Press any key to close.
pause >nul
