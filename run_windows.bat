REM -----------------------------------------------------------------------------
REM File: run_windows.bat
REM Purpose: Provides the run windows component of IAM Automation.
REM Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
REM Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
REM Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
REM Author / implementation: Miguel Fernandez.
REM Developed for: Kaiser Permanente NSES GWFM.
REM Project implementation and integration: Miguel Fernandez.
REM Third-party source, libraries, and dependencies retain their original licenses.
REM Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
REM -----------------------------------------------------------------------------

@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

echo [IAM] Project root: %ROOT_DIR%
if not exist "%ROOT_DIR%\iam_automation\templates\base.html" (
    echo [ERROR] The selected folder does not contain the current IAM web templates.
    echo [ERROR] Verify that Windows is running the repository checkout, not an old copy.
    pause
    exit /b 1
)
if not exist "%ROOT_DIR%\iam_automation\static\css\app.css" (
    echo [ERROR] The selected folder does not contain the current IAM stylesheet.
    pause
    exit /b 1
)
where git >nul 2>&1
if not errorlevel 1 for /f "delims=" %%R in ('git rev-parse --short HEAD 2^>nul') do echo [IAM] Git revision: %%R
if not errorlevel 1 for /f "delims=" %%B in ('git branch --show-current 2^>nul') do echo [IAM] Git branch: %%B

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
"%VENV_PYTHON%" -c "import alembic, flask, openpyxl, PySide6, sqlalchemy, waitress"
if errorlevel 1 goto :setup_failed
"%VENV_PYTHON%" -m compileall -q "%ROOT_DIR%\iam_automation" "%ROOT_DIR%\scripts" "%ROOT_DIR%\tests" "%ROOT_DIR%\run_app.py"
if errorlevel 1 goto :setup_failed
if /I "%IAM_RUN_TESTS%"=="1" (
    echo [IAM] Running project tests IAM_RUN_TESTS=1...
    "%VENV_PYTHON%" -m unittest discover -s "%ROOT_DIR%\tests" -q
    if errorlevel 1 goto :setup_failed
) else (
    echo [IAM] Skipping full test suite for startup. Set IAM_RUN_TESTS=1 to run it.
)

echo [IAM] Starting IAM Automation preflight and local webapp...
set "VENV_PYTHONW=%VENV_DIR%\Scripts\pythonw.exe"
if not exist "%VENV_PYTHONW%" set "VENV_PYTHONW=%VENV_PYTHON%"
set "IAM_LAUNCHER_LOG=%ROOT_DIR%\.iam_launcher.log"
type nul > "%IAM_LAUNCHER_LOG%"
start "IAM Automation" /D "%ROOT_DIR%" "%VENV_PYTHONW%" "%ROOT_DIR%\run_app.py"
echo [IAM] PySide6 control panel started. This console can now close.
exit /b 0

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
REM #endfile
