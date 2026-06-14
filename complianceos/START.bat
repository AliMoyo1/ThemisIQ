@echo off
echo.
echo  ====================================
echo   ARIA - Starting up...
echo  ====================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

:: Check Node.js (required for Word export)
node --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Node.js not found. Word export will be unavailable.
    echo           Download from: https://nodejs.org
    echo.
) else (
    :: Install docx npm package if needed
    if not exist "node_modules\docx" (
        echo [*] Installing docx package for Word export...
        npm install docx --save-quiet
        echo [OK] docx package installed
    )
)

:: Install Python dependencies if needed
if not exist ".deps_installed" (
    echo [*] Installing Python dependencies...
    pip install -r requirements.txt --quiet
    echo. > .deps_installed
    echo [OK] Dependencies installed
)

:: Initialize database
echo [*] Initialising database...
python database.py

echo.
echo  ====================================
echo   ARIA is running!
echo  ====================================
echo.
echo   On this laptop:
echo     http://localhost:8000
echo.
echo   From other devices on this network:
:: Print every non-loopback / non-APIPA IPv4 the laptop currently holds.
:: PowerShell is used (vs. parsing ipconfig) because ipconfig output is localized.
for /f "tokens=* usebackq" %%a in (`powershell -NoProfile -Command ^
  "Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } ^| Select-Object -ExpandProperty IPAddress"`) do (
    echo     http://%%a:8000
)
echo.
echo  ====================================
echo   First-time setup: run OPEN_FIREWALL.bat once
echo   as Administrator so other devices can connect.
echo  ====================================
echo.
echo  Press Ctrl+C to stop the server
echo.

:: Start the server
:: --host 0.0.0.0 makes ARIA reachable on the local network (not just localhost).
:: --reload picks up code changes without restarting; remove it for "real" deployments.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
