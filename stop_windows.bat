@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\stop_app.py"
) else (
  echo [ERROR] IAM virtual environment was not found.
  pause
)
endlocal
