REM -----------------------------------------------------------------------------
REM File: package_source.bat
REM Purpose: Provides the package source component of IAM Automation.
REM Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
REM Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
REM Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
REM Author: Miguel Fernandez.
REM Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
REM -----------------------------------------------------------------------------

@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON="

if defined IAM_PYTHON_BIN set "PYTHON=%IAM_PYTHON_BIN%"
if not defined PYTHON if exist "%ROOT%.venv\Scripts\python.exe" set "PYTHON=%ROOT%.venv\Scripts\python.exe"
if not defined PYTHON where py >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON where python >nul 2>nul && set "PYTHON=python"

if not defined PYTHON (
    echo [ERROR] Python 3.10 or newer is required to build the package.
    exit /b 1
)

%PYTHON% "%ROOT%scripts\package_source.py" %*
if errorlevel 1 exit /b %errorlevel%
echo [IAM] Package build completed.
endlocal
