@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

echo [IAM] Checking for Python 3.10 or newer...
set "PYTHON_EXE="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.10 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('py -3.10 -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%P"
    )
    if not defined PYTHON_EXE (
        for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%P"
    )
)

if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%P"
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] Python 3.10 or newer was not found. Install Python and enable the Python launcher.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required. Found:
    "%PYTHON_EXE%" --version
    pause
    exit /b 1
)

set "VENV_DIR=%ROOT_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [IAM] Creating virtual environment...
    "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    if errorlevel 1 goto :setup_failed
)

echo [IAM] Upgrading pip, setuptools, and wheel...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :setup_failed

echo [IAM] Installing or updating project packages...
"%VENV_PYTHON%" -m pip install --upgrade -r "%ROOT_DIR%\requirements.txt"
if errorlevel 1 goto :setup_failed

echo [IAM] Verifying installed packages and project tests...
"%VENV_PYTHON%" -m pip check
if errorlevel 1 goto :setup_failed
"%VENV_PYTHON%" -m compileall -q "%ROOT_DIR%\iam_automation" "%ROOT_DIR%\scripts" "%ROOT_DIR%\tests" "%ROOT_DIR%\run_app.py"
if errorlevel 1 goto :setup_failed
"%VENV_PYTHON%" -m unittest discover -s "%ROOT_DIR%\tests" -q
if errorlevel 1 goto :setup_failed

echo [IAM] Starting IAM Automation preflight and local webapp...
"%VENV_PYTHON%" "%ROOT_DIR%\run_app.py"
exit /b %errorlevel%

:setup_failed
echo [ERROR] Environment setup failed. Check the message above and your network/package access.
pause
exit /b 1
