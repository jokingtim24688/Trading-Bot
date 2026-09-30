@echo off
rem Run this on the Windows PC or VM that runs MetaTrader 5, so Trading Bot on your Mac (or Linux) can use MT5.
rem Keep MT5 open and logged in. The first run sets up Python packages and picks a secret token; it then shows the
rem address and token to type into the Mac app: Settings > MT5 connection. Close this window to stop the bridge.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python. This takes a minute...
  py -3.11 -m venv .venv || python -m venv .venv
)
".venv\Scripts\python.exe" -c "import MetaTrader5, numpy" 2>nul || ".venv\Scripts\python.exe" -m pip install MetaTrader5 numpy
if not exist "data" mkdir data
if not exist "data\mt5_bridge_token.txt" (
  powershell -NoProfile -Command "[guid]::NewGuid().ToString('N').Substring(0,20)" > "data\mt5_bridge_token.txt"
)
set /p TOKEN=<"data\mt5_bridge_token.txt"
echo.
echo In the Mac app, Settings ^> MT5 connection:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo    Bridge address:  http://%%b:18812
echo    Bridge token:    %TOKEN%
echo (Use the address on the same network as the Mac. Windows may ask to allow Python through the firewall: allow it.)
echo.
".venv\Scripts\python.exe" -m agent.mt5_remote serve --token %TOKEN%
pause
