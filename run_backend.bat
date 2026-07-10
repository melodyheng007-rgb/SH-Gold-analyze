@echo off
setlocal
cd /d "%~dp0backend"
set "PYTHON_CMD=python"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3.12 -V >nul 2>nul
  if %ERRORLEVEL%==0 (
    set "PYTHON_CMD=py -3.12"
  ) else (
    py -3.11 -V >nul 2>nul
    if %ERRORLEVEL%==0 set "PYTHON_CMD=py -3.11"
  )
)

if not exist .venv (
  %PYTHON_CMD% -m venv .venv
)
call .venv\Scripts\activate
python -c "import sys; raise SystemExit(0 if sys.version_info < (3, 14) else 'Python 3.14 is not supported by this pinned NumPy/Pandas stack. Delete backend\\.venv and rerun this script with Python 3.12 or 3.11 installed.')"
if errorlevel 1 (
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8001
pause
