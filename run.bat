@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Not installed yet. Run install.bat first.
  exit /b 1
)
.venv\Scripts\python linkedin_scheduler.py %*
