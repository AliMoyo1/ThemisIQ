@echo off
:: ARIA — Windows Firewall helper.
:: Opens TCP port 8000 inbound on the *Private* network profile only, so the
:: app is reachable from devices on the same Wi-Fi / LAN but NOT from public
:: networks (coffee-shop Wi-Fi, hotel networks, etc.).
::
:: Run this ONCE. You only need to re-run it if the rule gets removed
:: (e.g. after a Windows reinstall or if you change the port).

setlocal

:: ── Self-elevate to Administrator ────────────────────────────────────────────
>nul 2>&1 net session
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  ====================================
echo   ARIA - Windows Firewall setup
echo  ====================================
echo.
echo  Opening TCP 8000 inbound (Private profile only).
echo.

:: Remove any existing rule with the same name so we don't accumulate duplicates.
netsh advfirewall firewall delete rule name="ARIA on TCP 8000" >nul 2>&1

netsh advfirewall firewall add rule ^
    name="ARIA on TCP 8000" ^
    description="Allow inbound connections to ARIA on TCP 8000 (Private networks only)" ^
    dir=in action=allow protocol=TCP localport=8000 profile=private enable=yes

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to add firewall rule. See message above.
    pause
    exit /b 1
)

echo.
echo  ====================================
echo   Done. ARIA can now be reached from
echo   other devices on this local network.
echo  ====================================
echo.
echo   To remove this rule later, run:
echo     netsh advfirewall firewall delete rule name="ARIA on TCP 8000"
echo.
pause
