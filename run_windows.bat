@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not defined IAM_DEV_AUTO_APPROVE_USERS set "IAM_DEV_AUTO_APPROVE_USERS=1"
if not defined IAM_DEV_DEFAULT_ROLE set "IAM_DEV_DEFAULT_ROLE=REQUESTER"

echo [IAM] Checking for Python 3.10 or newer...
set "PYTHON_EXE=%IAM_PYTHON_BIN%"

if defined PYTHON_EXE "%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if defined PYTHON_EXE if errorlevel 1 set "PYTHON_EXE="
if defined PYTHON_EXE goto :python_found

where py >nul 2>&1
if not errorlevel 1 for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%P"
if defined PYTHON_EXE goto :python_found

for %%C in (python.exe python3.exe) do (
    where %%C >nul 2>&1
    if not errorlevel 1 for /f "delims=" %%P in ('%%C -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%P"
)
if defined PYTHON_EXE goto :python_found

for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do call :try_python "%%~D\python.exe"
for /d %%D in ("%ProgramFiles%\Python*") do call :try_python "%%~D\python.exe"
for /d %%D in ("%ProgramFiles(x86)%\Python*") do call :try_python "%%~D\python.exe"
if defined PYTHON_EXE goto :python_found

for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do call :try_python "%%B\python.exe"
for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do call :try_python "%%B\python.exe"
for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\WOW6432Node\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do call :try_python "%%B\python.exe"
if defined PYTHON_EXE goto :python_found

if not defined PYTHON_EXE (
    echo [ERROR] Python 3.10 or newer was not found. Install Python and enable the Python launcher.
    pause
    exit /b 1
)

:python_found

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

:try_python
if defined PYTHON_EXE exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=%~1"
exit /b 0

:setup_failed
echo [ERROR] Environment setup failed. Check the message above and your network/package access.
pause
exit /b 1
