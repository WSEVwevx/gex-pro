@echo off
rem One-time Schwab login. Repeat every 7 days (Schwab's limit). See docs\SCHWAB_SETUP.md.
cd /d "%~dp0"
title Schwab login
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py"
"%PY%" -m gexsys --log-level WARNING schwab-login
echo.
echo If START.bat is already running, close it and start it again to switch to Schwab data.
pause
