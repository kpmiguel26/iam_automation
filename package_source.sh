#!/usr/bin/env sh
# -----------------------------------------------------------------------------
# File: package_source.sh
# Purpose: Provides the package source component of IAM Automation.
# Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
# Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
# Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
# Author / implementation: Miguel Fernandez.
# Developed for: Kaiser Permanente NSES GWFM.
# Project implementation and integration: Miguel Fernandez.
# Third-party source, libraries, and dependencies retain their original licenses.
# Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
# -----------------------------------------------------------------------------

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
#endfile
