#!/usr/bin/env bash
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
      if "$candidate" -c 'import sys; import tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "$candidate")"
        break
      fi
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python 3.10 or newer with tkinter was not found. Install Python or set IAM_PYTHON_BIN."
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
"$VENV_PYTHON" -m compileall -q "$ROOT_DIR/iam_automation" "$ROOT_DIR/scripts" "$ROOT_DIR/tests" "$ROOT_DIR/run_app.py"
"$VENV_PYTHON" -m unittest discover -s "$ROOT_DIR/tests" -q

echo "[IAM] Starting IAM Automation preflight and local webapp..."
exec "$VENV_PYTHON" "$ROOT_DIR/run_app.py"
