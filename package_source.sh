#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -n "${IAM_PYTHON_BIN:-}" ]; then
    PYTHON=$IAM_PYTHON_BIN
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON=$ROOT/.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
else
    echo "[ERROR] Python 3.10 or newer is required to build the package." >&2
    exit 1
fi

exec "$PYTHON" "$ROOT/scripts/package_source.py" "$@"
