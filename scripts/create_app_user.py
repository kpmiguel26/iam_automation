from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from iam_automation.database import initialize_runtime_database
from iam_automation.runtime_sync import project_runtime_path, publish_runtime_snapshot
from iam_automation.workspace_layout import ensure_sharepoint_structure


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reset an IAM Automation application account.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="REQUESTER")
    parser.add_argument("--path", type=Path, default=project_runtime_path())
    parser.add_argument("--publish-root", type=Path)
    parser.add_argument("--actor", default="application-account-bootstrap")
    args = parser.parse_args()

    password = getpass.getpass("Application password: ")
    confirmation = getpass.getpass("Confirm application password: ")
    if not password or password != confirmation:
        parser.error("Passwords are empty or do not match.")

    local = initialize_runtime_database(args.path)
    connection = sqlite3.connect(local)
    try:
        connection.execute(
            "INSERT INTO app_users (username, display_name, password_hash, active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, active = 1, updated_at_utc = datetime('now')",
            (args.username, args.username, generate_password_hash(password)),
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
    finally:
        connection.close()

    result = {"ok": True, "local_path": str(local), "app_username": args.username, "role": args.role.upper()}
    if args.publish_root:
        ensure_sharepoint_structure(args.publish_root)
        published = args.publish_root / "database" / "snapshots" / "iam_runtime.sqlite"
        snapshot = publish_runtime_snapshot(local, published, actor=args.actor)
        result.update({"published_path": str(snapshot.published_path), "checksum": snapshot.checksum})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
