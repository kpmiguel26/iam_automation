#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# File: run.sh
# Purpose: Provides the run component of IAM Automation.
# Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
# Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
# Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
# Author / implementation: Miguel Fernandez.
# Developed for: Kaiser Permanente NSES GWFM.
# Project implementation and integration: Miguel Fernandez.
# Third-party source, libraries, and dependencies retain their original licenses.
# Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
# -----------------------------------------------------------------------------

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export IAM_DEV_DEFAULT_ROLE="${IAM_DEV_DEFAULT_ROLE:-REQUESTER}"

echo "[IAM] Checking for Python 3.10 or newer..."
PYTHON_BIN="${IAM_PYTHON_BIN:-}"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

# Reuse the existing virtual environment first. This keeps the launcher
# independent from changes to the user's shell PATH after setup.
if [[ -z "$PYTHON_BIN" && -x "$VENV_PYTHON" ]]; then
  if "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PYTHON_BIN="$VENV_PYTHON"
    echo "[IAM] Reusing existing virtual environment: $VENV_PYTHON"
  fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "$candidate")"
        break
      fi
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python 3.10 or newer was not found. Install Python or set IAM_PYTHON_BIN."
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "[ERROR] Python 3.10 or newer is required. Found:"
  "$PYTHON_BIN" --version
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[IAM] Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "[IAM] Upgrading pip, setuptools, and wheel..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

echo "[IAM] Installing or updating project packages..."
"$VENV_PYTHON" -m pip install --upgrade -r "$ROOT_DIR/requirements.txt"

echo "[IAM] Verifying installed packages and project tests..."
"$VENV_PYTHON" -m pip check
"$VENV_PYTHON" -c 'import alembic, flask, openpyxl, PySide6, sqlalchemy, waitress'
"$VENV_PYTHON" -m compileall -q "$ROOT_DIR/iam_automation" "$ROOT_DIR/scripts" "$ROOT_DIR/tests" "$ROOT_DIR/run_app.py"
if [[ "${IAM_RUN_TESTS:-0}" == "1" ]]; then
  echo "[IAM] Running project tests (IAM_RUN_TESTS=1)..."
  "$VENV_PYTHON" -m unittest discover -s "$ROOT_DIR/tests" -q
else
  echo "[IAM] Skipping full test suite for startup. Set IAM_RUN_TESTS=1 to run it."
fi

echo "[IAM] Starting IAM Automation preflight and local webapp..."
export IAM_LAUNCHER_LOG="${IAM_LAUNCHER_LOG:-$ROOT_DIR/.iam_launcher.log}"
: > "$IAM_LAUNCHER_LOG"
exec "$VENV_PYTHON" "$ROOT_DIR/run_app.py"
#endfile
