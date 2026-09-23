@echo off
rem Double-click to open the Trading Bot app. This window closes by itself once the app is open.
rem First run creates the Python environment automatically; later runs update the app first.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: setting up Python environment. This takes a few minutes...
  py -3.11 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
rem get the latest version (quietly; carries on offline or if git isn't set up)
if exist ".git" git pull --ff-only -q >nul 2>&1
rem install packages only when requirements.txt changed since the last install
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || (
  echo Installing packages...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
)
rem pythonw = no console window; output goes to logs\app.log
start "" ".venv\Scripts\pythonw.exe" -m app.main
exit
