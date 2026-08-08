"""
File: scripts/submit_change_request.py
Purpose: Provides an operational utility for submit change request.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation import __version__
from iam_automation.change_request import new_request, submit_request
from iam_automation.identity import CurrentUser, ROLE_REQUESTER


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an immutable IAM change request JSON file.")
    parser.add_argument("--pending-folder", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--computer", default="LOCAL")
    parser.add_argument("--operation-type", default="UPDATE_EMPLOYEE")
    parser.add_argument("--entity-id", required=True)
    parser.add_argument("--expected-record-version", type=int, required=True)
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()

    user = CurrentUser(args.username, args.computer, (ROLE_REQUESTER,))
    request = new_request(
        user=user,
        application_version=__version__,
        operation_type=args.operation_type,
        entity_type="Employee",
        entity_id=args.entity_id,
        expected_record_version=args.expected_record_version,
        payload=json.loads(args.payload_json),
        reason=args.reason,
    )
    path = submit_request(request, args.pending_folder)
    print(json.dumps({"request_id": request.request_id, "path": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
