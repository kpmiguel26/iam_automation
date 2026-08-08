"""
File: scripts/sync_runtime_database.py
Purpose: Provides an operational utility for sync runtime database.
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

from iam_automation.runtime_sync import find_published_runtime_db, project_runtime_path, publish_runtime_snapshot, sync_runtime_snapshot
from iam_automation.workspace_layout import ensure_sharepoint_structure


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the runtime SQLite snapshot with the selected SharePoint path.")
    parser.add_argument("sharepoint_root", type=Path)
    parser.add_argument("--publish", action="store_true", help="Publish the local project runtime.sqlite back to SharePoint.")
    parser.add_argument("--actor", default="manual-admin", help="Actor recorded in the published manifest.")
    parser.add_argument("--expected-checksum", help="Expected current published checksum for optimistic concurrency.")
    args = parser.parse_args()
    ensure_sharepoint_structure(args.sharepoint_root)
    published = find_published_runtime_db(args.sharepoint_root)
    if not published:
        print(json.dumps({"ok": False, "error": "Published runtime SQLite was not found under the selected path."}, indent=2))
        return 1
    if args.publish:
        result = publish_runtime_snapshot(project_runtime_path(), published, actor=args.actor, expected_checksum=args.expected_checksum)
    else:
        result = sync_runtime_snapshot(published, project_runtime_path())
    print(json.dumps({"ok": True, "local_path": str(result.local_path), "published_path": str(result.published_path), "checksum": result.checksum, "schema_version": result.schema_version}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
