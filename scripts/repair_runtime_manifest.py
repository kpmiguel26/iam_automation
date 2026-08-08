#!/usr/bin/env python3
"""
File: scripts/repair_runtime_manifest.py
Purpose: Explicitly repair a runtime SQLite manifest after integrity validation.
Responsibilities: Exposes or coordinates: main.
Dependencies: argparse, iam_automation
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.runtime_sync import repair_runtime_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Published iam_runtime.sqlite path")
    parser.add_argument("--confirm", action="store_true", help="Write the repaired manifest")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("Refusing to modify the manifest without --confirm")
    manifest = repair_runtime_manifest(args.database)
    print(f"Repaired manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
