@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="8000" goto configured
if "%~1"=="8001" goto configured
echo Usage: start_api.cmd 8000 ^| 8001
exit /b 2

:configured
rem Explicit per-process configuration avoids stale Task Scheduler environment.
set "JEWELRY_API_PORT=%~1"
set "VISION_API_URL=http://10.77.0.2:11434"
rem Preserve the existing model, provider, API bind address and credentials.
if not exist logs mkdir logs
if not exist logs exit /b 1
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" -u api.py >> logs\api.log 2>&1
exit /b %errorlevel%
