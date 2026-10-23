@echo off
rem Starts the GEX service for NQ + ES and opens the website.
rem Data: CME NQ/ES options on futures via Databento once DATABENTO_SETUP.bat has saved a key, else Cboe's free feed.
cd /d "%~dp0"
title GEX Levels service - keep this window open
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
"%PY%" -m gexsys --log-level WARNING serve --auto
echo.
echo The service stopped. If it says the port is in use, it is probably already running in another window.
pause
