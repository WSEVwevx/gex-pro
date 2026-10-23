@echo off
rem One-time setup: saves your Databento API key on this PC (not in OneDrive/GitHub) and tests it.
cd /d "%~dp0"
title Databento setup
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py"
"%PY%" -m gexsys --log-level WARNING databento-setup
echo.
pause
