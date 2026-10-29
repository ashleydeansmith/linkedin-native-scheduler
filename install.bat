@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.9 or later is needed. Download it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH". Then run install.bat again.
  pause
  exit /b 1
)
echo Creating a private Python environment in .venv ...
%PY% -m venv .venv || goto :fail
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || goto :fail
echo Downloading the Firefox that Playwright drives (about 90 MB) ...
.venv\Scripts\python -m playwright install firefox || goto :fail
echo.
echo Installed. Next: run.bat login
pause
exit /b 0
:fail
echo Install failed. Read the message above.
pause
exit /b 1
