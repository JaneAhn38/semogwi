@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating .venv and installing packages...
  py -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
)

echo.
echo   Semogwi web: http://127.0.0.1:8000
echo   Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:fail
echo [error] Setup failed. Check that Python 3 and the "py" launcher are installed.
exit /b 1
