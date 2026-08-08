REM -----------------------------------------------------------------------------
REM File: stop_windows.bat
REM Purpose: Provides the stop windows component of IAM Automation.
REM Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
REM Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
REM Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
REM Author: Miguel Fernandez.
REM Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
REM -----------------------------------------------------------------------------

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
