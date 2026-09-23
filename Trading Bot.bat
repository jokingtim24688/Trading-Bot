@echo off
rem Double-click to open the Trading Bot app. First run creates the Python environment automatically.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: setting up Python environment. This takes a few minutes...
  py -3.11 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" -m app.main
