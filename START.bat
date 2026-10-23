@echo off
rem Starts GEX PRO for NQ + ES and opens the website.
rem Data: Cboe's free feed - SPX+SPY options for ES, NDX+QQQ for NQ (15 minutes delayed).
cd /d "%~dp0"
title GEX PRO - keep this window open
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py"
echo Checking dependencies...
"%PY%" -m pip install --disable-pip-version-check -q --user -r requirements.txt
if errorlevel 1 (
  echo.
  echo Could not install dependencies. Is Python 3.12 installed?  winget install Python.Python.3.12 --scope user
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765
"%PY%" -m gexpro --log-level WARNING serve --auto
echo.
echo The service stopped. If it says the port is in use, it is probably already running in another window.
pause
