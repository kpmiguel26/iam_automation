from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.lock import LockConflict, acquire_lock, release_lock


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 4: application-level lock behavior.")
    parser.add_argument("lock_path", type=Path)
    args = parser.parse_args()

    first = acquire_lock(
        args.lock_path,
        user=os.environ.get("USERNAME", "poc-user"),
        computer=os.environ.get("COMPUTERNAME", socket.gethostname()),
        operation="poc-lock-test",
        database_checksum="demo",
        database_version="demo",
        application_version="0.1.0-poc",
    )
    conflict_detected = False
    try:
        acquire_lock(
            args.lock_path,
            user="second-user",
            computer="second-computer",
            operation="poc-second-lock",
            database_checksum="demo",
            database_version="demo",
            application_version="0.1.0-poc",
        )
    except LockConflict:
        conflict_detected = True
    finally:
        released = release_lock(args.lock_path, first.lock_id)

    print(json.dumps({"conflict_detected": conflict_detected, "released": released}, indent=2))
    return 0 if conflict_detected and released else 1


if __name__ == "__main__":
    raise SystemExit(main())
