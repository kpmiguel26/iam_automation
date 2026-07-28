from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .migrations import v001_initial_schema, v002_notification_indexes


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    upgrade: object
    source_path: Path


MIGRATIONS = (
    Migration(v001_initial_schema.VERSION, v001_initial_schema.DESCRIPTION, v001_initial_schema.upgrade, Path(v001_initial_schema.__file__)),
    Migration(v002_notification_indexes.VERSION, v002_notification_indexes.DESCRIPTION, v002_notification_indexes.upgrade, Path(v002_notification_indexes.__file__)),
)


def apply_pending_migrations(database_path: Path, actor: str = "system") -> tuple[str, ...]:
    """Apply ordered migrations atomically and return versions applied now."""
    path = database_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    applied_now: list[str] = []
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at_utc TEXT NOT NULL,
                applied_by TEXT NOT NULL
            )
            """
        )
        connection.commit()
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            checksum = hashlib.sha256(migration.source_path.read_bytes()).hexdigest()
            connection.execute("BEGIN")
            try:
                migration.upgrade(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, description, checksum, applied_at_utc, applied_by) VALUES (?, ?, ?, ?, ?)",
                    (migration.version, migration.description, checksum, datetime.now(timezone.utc).isoformat(), actor),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            applied_now.append(migration.version)
        return tuple(applied_now)
    finally:
        connection.close()


def applied_migrations(database_path: Path) -> tuple[str, ...]:
    path = database_path.expanduser().resolve()
    if not path.is_file():
        return ()
    connection = sqlite3.connect(path)
    try:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone()
        if not exists:
            return ()
        return tuple(row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version"))
    finally:
        connection.close()
