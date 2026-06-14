@echo off
REM ============================================================
REM  BCM Sentinel - Windows launcher
REM  By Ali Moyo
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title BCM Sentinel

echo.
echo   ============================================================
echo     BCM Sentinel - starting up
echo     By Ali Moyo
echo   ============================================================
echo.

REM ---- Check Node is installed ----
where node >nul 2>nul
if errorlevel 1 (
  echo   [ERROR] Node.js was not found on your PATH.
  echo           Install Node.js 22.5 or newer from https://nodejs.org/
  echo           Then close this window and double-click start.bat again.
  echo.
  pause
  exit /b 1
)

REM ---- Show Node version ----
for /f "tokens=*" %%v in ('node -v') do set NODE_VERSION=%%v
echo   Using Node %NODE_VERSION%

REM ---- Require Node 22.5 or newer (needs built-in node:sqlite) ----
node -e "var v=process.versions.node.split('.').map(Number); if (v[0]<22 || (v[0]===22 && v[1]<5)) { process.exit(2); }" 2>nul
if errorlevel 2 (
  echo.
  echo   [ERROR] Node %NODE_VERSION% is too old.
  echo           BCM Sentinel uses the built-in node:sqlite module which requires Node 22.5+.
  echo           Please install the latest LTS from https://nodejs.org/
  echo.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo   [WARN] Could not verify Node version. Continuing anyway.
)

REM ---- Install dependencies on first run ----
if not exist node_modules (
  echo.
  echo   Installing dependencies ^(first run only^)...
  call npm install
  if errorlevel 1 (
    echo.
    echo   [ERROR] npm install failed. Scroll up to see the reason.
    pause
    exit /b 1
  )
)

REM ---- First-time seed ----
if not exist data\bcm.db (
  echo.
  echo   Seeding demo workspace ^(demo@acme.test / demo12345^)...
  call npm run seed
  if errorlevel 1 (
    echo.
    echo   [WARN] Seed failed. You can still use the app; it will be empty.
  )
)

REM ---- Default port (overridable) ----
if "%PORT%"=="" set PORT=3000

REM ---- Detect this machine's LAN IPv4 address ----
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do (
    if "!LAN_IP!"=="" set "LAN_IP=%%b"
  )
)
REM Strip trailing space just in case
if defined LAN_IP set "LAN_IP=!LAN_IP: =!"

REM ---- One-time Windows Firewall rule so other laptops can reach us ----
REM Skip silently if already present or if we don't have admin rights.
netsh advfirewall firewall show rule name="BCM Sentinel" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Adding Windows Firewall rule so others on the network can reach BCM Sentinel...
  netsh advfirewall firewall add rule name="BCM Sentinel" dir=in action=allow protocol=TCP localport=%PORT% profile=private,domain >nul 2>nul
  if errorlevel 1 (
    echo   [WARN] Could not add firewall rule automatically.
    echo          If colleagues can't connect, right-click start.bat and pick "Run as administrator"
    echo          once to create the rule, or ask IT to allow inbound TCP %PORT% for this app.
  ) else (
    echo   Firewall rule added.
  )
)

echo.
echo   ============================================================
echo     BCM Sentinel is starting on port %PORT%
echo.
echo     On this laptop:
echo       http://localhost:%PORT%/login
if defined LAN_IP (
  echo.
  echo     Share with colleagues on the corporate network:
  echo       http://!LAN_IP!:%PORT%/login
)
echo.
echo     Press Ctrl+C to stop.
echo   ============================================================
echo.

node server.js
set EXITCODE=%ERRORLEVEL%

echo.
if not "%EXITCODE%"=="0" (
  echo   [ERROR] Server exited with code %EXITCODE%.
  echo           Common causes:
  echo             * Port %PORT% already in use  ^(set PORT=3001 in .env or use: set PORT=3001 ^&^& start.bat^)
  echo             * Missing or invalid .env file
  echo             * Dependency missing      ^(delete node_modules and run start.bat again^)
) else (
  echo   Server stopped cleanly.
)
echo.
pause
endlocal
