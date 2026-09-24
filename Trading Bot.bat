@echo off
rem Double-click to open the Trading Bot app. This window closes by itself once the app is open.
rem First run creates the Python environment automatically; later runs update the app first.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: setting up Python environment. This takes a few minutes...
  py -3.11 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
rem Everything below is one block: cmd reads it all before running it, so an update that rewrites this file
rem can't garble the rest of this run.
(
  rem get the latest version from GitHub with app\update.py: it fixes the branch and tracking, saves local edits,
  rem says what happened in logs\update.log and in the app, and carries on offline
  echo Checking for updates...
  ".venv\Scripts\python.exe" -m app.update
  rem install packages only when requirements.txt changed since the last install
  fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || (
    echo Installing packages...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
  )
  rem pythonw = no console window; output goes to logs\app.log
  start "" ".venv\Scripts\pythonw.exe" -m app.main
  exit
)
