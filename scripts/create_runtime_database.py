"""
File: scripts/create_runtime_database.py
Purpose: Provides an operational utility for create runtime database.
Responsibilities: Exposes or coordinates: main.
Dependencies: argparse, iam_automation, werkzeug
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.database import initialize_runtime_database
from iam_automation.runtime_sync import project_runtime_path, publish_runtime_snapshot
from iam_automation.workspace_layout import ensure_sharepoint_structure
from werkzeug.security import generate_password_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the local runtime SQLite database and optionally publish it.")
    parser.add_argument("--path", type=Path, default=project_runtime_path())
    parser.add_argument("--publish-root", type=Path, help="SharePoint root where the runtime snapshot should be published.")
    parser.add_argument("--actor", default="initial-bootstrap")
    parser.add_argument("--username", help="Optional initial approved username for local development.")
    parser.add_argument("--role", default="REQUESTER", help="Role for --username.")
    parser.add_argument("--app-username", help="Optional application login username.")
    parser.add_argument("--app-password", help="Application login password; stored only as a hash.")
    args = parser.parse_args()
    local = initialize_runtime_database(args.path)
    if args.username:
        connection = sqlite3.connect(local)
        connection.execute(
            "INSERT INTO approved_users (username, display_name, active) VALUES (?, ?, 1) ON CONFLICT(username) DO UPDATE SET active = 1",
            (args.username, args.username),
        )
        connection.execute(
            "INSERT INTO roles (role_name, description, active) VALUES (?, '', 1) ON CONFLICT(role_name) DO UPDATE SET active = 1",
            (args.role.upper(),),
        )
        connection.execute(
            "INSERT OR IGNORE INTO user_roles (username, role_name) VALUES (?, ?)",
            (args.username, args.role.upper()),
        )
        connection.commit()
        connection.close()
    if args.app_username or args.app_password:
        if not args.app_username or not args.app_password:
            parser.error("--app-username and --app-password must be provided together")
        connection = sqlite3.connect(local)
        connection.execute(
            "INSERT INTO app_users (username, display_name, password_hash, active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, active = 1, updated_at_utc = datetime('now')",
            (args.app_username, args.app_username, generate_password_hash(args.app_password)),
        )
        connection.execute(
            "INSERT INTO roles (role_name, description, active) VALUES (?, '', 1) ON CONFLICT(role_name) DO UPDATE SET active = 1",
            (args.role.upper(),),
        )
        connection.execute(
            "INSERT OR IGNORE INTO user_roles (username, role_name) VALUES (?, ?)",
            (args.app_username, args.role.upper()),
        )
        connection.commit()
        connection.close()
    result = {"ok": True, "local_path": str(local)}
    if args.publish_root:
        ensure_sharepoint_structure(args.publish_root)
        published = args.publish_root / "database" / "snapshots" / "iam_runtime.sqlite"
        snapshot = publish_runtime_snapshot(local, published, actor=args.actor)
        result.update({"published_path": str(snapshot.published_path), "checksum": snapshot.checksum})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
