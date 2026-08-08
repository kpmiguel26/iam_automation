"""
File: scripts/admin_import_pending_requests.py
Purpose: Provides an operational utility for admin import pending requests.
Responsibilities: Exposes or coordinates: main.
Dependencies: argparse, iam_automation
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.change_request import import_pending_requests
from iam_automation.identity import CurrentUser, ROLE_WRITER


def main() -> int:
    parser = argparse.ArgumentParser(description="Admin POC: import pending immutable request files.")
    parser.add_argument("--requests-root", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--computer", default="ADMIN-PC")
    parser.add_argument("--batch-id", default="")
    args = parser.parse_args()

    user = CurrentUser(args.username, args.computer, (ROLE_WRITER,))
    if not user.is_writer:
        raise PermissionError("Only ADMINISTRATOR/WRITER can import pending requests.")

    batch_id = args.batch_id or str(uuid.uuid4())
    root = args.requests_root
    summary = import_pending_requests(
        pending_folder=root / "pending",
        imported_folder=root / "imported",
        quarantine_folder=root / "quarantine",
        processed_registry_path=root / "processed_requests.jsonl",
        batch_id=batch_id,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
