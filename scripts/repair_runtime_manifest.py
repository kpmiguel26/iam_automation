#!/usr/bin/env python3
"""Explicitly repair a runtime SQLite manifest after integrity validation."""

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
