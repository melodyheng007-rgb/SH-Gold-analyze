@echo off
setlocal EnableExtensions
title SH Market Analyzer V3.7 - Frontend
cd /d "%~dp0frontend"

set "FRONTEND_URL=http://127.0.0.1:5173"

echo.
echo =====================================================
echo   SH Market Analyzer V3.7 - Frontend Launcher
echo =====================================================

powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $response=Invoke-WebRequest -Uri '%FRONTEND_URL%' -UseBasicParsing -TimeoutSec 3; if ($response.StatusCode -eq 200 -and $response.Content -match 'SH Market Analyzer V3.7') { Write-Host '[ONLINE] SH Frontend is already running.'; exit 0 }; exit 1"
if not errorlevel 1 (
  if /I not "%SH_NO_BROWSER%"=="1" (
    echo Opening %FRONTEND_URL% ...
    start "" "%FRONTEND_URL%"
  )
  echo Nothing else needs to be started.
  exit /b 0
)

powershell -NoProfile -Command "$listener=Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $listener) { exit 0 }; $process=Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue; Write-Host ('[ERROR] Port 5173 is used by PID {0} ({1}), but it is not the SH frontend.' -f $listener.OwningProcess, $process.ProcessName); exit 2"
if errorlevel 2 (
  echo Close the process using port 5173 and run this launcher again.
  pause
  exit /b 2
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js was not found. Install the current Node.js LTS release first.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found. Repair the Node.js installation first.
  pause
  exit /b 1
)

if not exist "node_modules\vite\bin\vite.js" (
  echo [SETUP] Installing frontend dependencies. This is only needed after setup or an upgrade...
  call npm install
  if errorlevel 1 (
    echo [ERROR] Frontend dependency installation failed.
    pause
    exit /b 1
  )
)

echo [START] Frontend: %FRONTEND_URL%
echo [START] LAN access is enabled on port 5173.
echo Press Ctrl+C to stop the frontend.
echo.
call npm run dev
set "FRONTEND_EXIT=%ERRORLEVEL%"
echo.
echo [STOPPED] Frontend exited with code %FRONTEND_EXIT%.
pause
exit /b %FRONTEND_EXIT%
