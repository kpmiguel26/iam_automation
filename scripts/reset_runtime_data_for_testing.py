"""Purge runtime test data while preserving application identity and configuration."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


OPERATIONAL_TABLES = (
    "approval_assignments",
    "change_requests",
    "publication_queue",
    "notifications",
    "import_batches",
    "quarantine_records",
    "ingestion_records",
    "file_observations",
    "worker_discrepancies",
    "worker_engagements",
    "worker_identifiers",
    "worker_merge_events",
    "worker_profile_versions",
    "worker_source_lineage",
    "worker_source_profiles",
    "workers",
)

PRESERVED_TABLES = (
    "app_metadata",
    "alembic_version",
    "app_users",
    "approved_users",
    "roles",
    "user_roles",
    "admin_delegations",
    "session_revocations",
    "temporary_elevations",
    "template_mappings",
    "system_profiles",
)


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def purge(database: Path) -> None:
    if not database.is_file():
        raise SystemExit(f"Published database not found: {database}")

    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=OFF")
        available = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [table for table in OPERATIONAL_TABLES + PRESERVED_TABLES if table not in available]
        if missing:
            raise SystemExit(f"Unexpected schema; missing tables: {', '.join(missing)}")

        users_before = {table: _count(connection, table) for table in ("app_users", "approved_users", "roles", "user_roles")}
        operational_before = {table: _count(connection, table) for table in OPERATIONAL_TABLES}

        connection.execute("BEGIN IMMEDIATE")
        for table in OPERATIONAL_TABLES:
            connection.execute(f'DELETE FROM "{table}"')
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")

        users_after = {table: _count(connection, table) for table in users_before}
        operational_after = {table: _count(connection, table) for table in OPERATIONAL_TABLES}
        if users_before != users_after:
            raise RuntimeError(f"User/access counts changed unexpectedly: {users_before} -> {users_after}")
        if any(operational_after.values()):
            raise RuntimeError(f"Operational data remains: {operational_after}")

        print("PURGE=OK")
        print(f"DATABASE={database}")
        print(f"USERS_PRESERVED={users_after}")
        print(f"OPERATIONAL_BEFORE={operational_before}")
        print(f"DATABASE_SIZE={database.stat().st_size}")
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--confirm", action="store_true", help="required confirmation for destructive test reset")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Refusing to purge without --confirm")
    purge(args.database.resolve())


if __name__ == "__main__":
    main()
