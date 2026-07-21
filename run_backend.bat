@echo off
setlocal EnableExtensions
title SH Market Analyzer V3.8 - Backend
cd /d "%~dp0backend"

set "BACKEND_URL=http://127.0.0.1:8001"
set "SH_LOCAL_OWNER_MODE=true"
set "VENV_PY=.venv\Scripts\python.exe"
set "PYTHON_CMD="

echo.
echo =====================================================
echo   SH Market Analyzer V3.8 - Backend Launcher
echo =====================================================

powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $health=Invoke-RestMethod -Uri '%BACKEND_URL%/api/health' -TimeoutSec 3; if ($health.app -eq 'SH Market Analyzer' -and $health.status -eq 'OK') { Write-Host ('[ONLINE] {0} {1} is already running.' -f $health.app, $health.version); exit 0 }; exit 1"
if not errorlevel 1 (
  echo URL: %BACKEND_URL%
  echo Nothing else needs to be started.
  echo.
  pause
  exit /b 0
)

powershell -NoProfile -Command "$listener=Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $listener) { exit 0 }; $process=Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue; Write-Host ('[ERROR] Port 8001 is used by PID {0} ({1}), but it is not the SH backend.' -f $listener.OwningProcess, $process.ProcessName); exit 2"
if errorlevel 2 (
  echo Close the process using port 8001 and run this launcher again.
  pause
  exit /b 2
)

if exist "%VENV_PY%" goto dependencies

echo [SETUP] A usable backend virtual environment was not found.
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -V >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
  if not defined PYTHON_CMD (
    py -3.11 -V >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
  )
)

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD (
  echo [ERROR] Python 3.12 or Python 3.11 was not found.
  echo Install Python 3.12, enable the Python launcher, then run this file again.
  pause
  exit /b 1
)

if exist .venv (
  echo [ERROR] The backend .venv folder exists but its Python executable is missing.
  echo Rename or remove backend\.venv, then run this launcher again.
  pause
  exit /b 1
)

echo [SETUP] Creating backend\.venv with %PYTHON_CMD%...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
  echo [ERROR] Could not create the backend virtual environment.
  pause
  exit /b 1
)

:dependencies
"%VENV_PY%" -c "import fastapi, uvicorn, pandas, numpy, multipart, requests" >nul 2>nul
if errorlevel 1 (
  echo [SETUP] Installing backend dependencies. This is only needed after setup or an upgrade...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed.
    pause
    exit /b 1
  )
)

echo [START] Backend: %BACKEND_URL%
echo [START] LAN access is enabled on port 8001.
echo Press Ctrl+C to stop the backend.
echo.
"%VENV_PY%" -m uvicorn app:app --host 0.0.0.0 --port 8001
set "BACKEND_EXIT=%ERRORLEVEL%"
echo.
echo [STOPPED] Backend exited with code %BACKEND_EXIT%.
pause
exit /b %BACKEND_EXIT%
