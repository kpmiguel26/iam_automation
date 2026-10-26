"""Namespaced, additive SQLite schema owned by the parallel engine."""

from __future__ import annotations

import sqlite3
from pathlib import Path


ENGINE_SCHEMA_VERSION = 4


DDL = (
    """CREATE TABLE IF NOT EXISTS engine_v2_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS engine_v2_object_template_approvals (
        object_template_version_id TEXT PRIMARY KEY,
        approved_by TEXT NOT NULL,
        approved_at_utc TEXT NOT NULL,
        FOREIGN KEY(object_template_version_id)
            REFERENCES employee_template_versions(employee_template_version_id)
    )""",
    """CREATE TABLE IF NOT EXISTS engine_v2_batches (
        batch_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        source_version_id TEXT NOT NULL,
        object_template_version_id TEXT NOT NULL,
        source_file TEXT NOT NULL,
        source_checksum TEXT NOT NULL,
        status TEXT NOT NULL,
        total_rows INTEGER NOT NULL DEFAULT 0,
        evidence_rows INTEGER NOT NULL DEFAULT 0,
        quarantined_rows INTEGER NOT NULL DEFAULT 0,
        objects_created INTEGER NOT NULL DEFAULT 0,
        objects_linked INTEGER NOT NULL DEFAULT 0,
        started_at_utc TEXT NOT NULL,
        completed_at_utc TEXT,
        message TEXT NOT NULL DEFAULT '',
        authorized_by TEXT NOT NULL DEFAULT '',
        authorized_at_utc TEXT,
        UNIQUE(source_id, source_version_id, object_template_version_id, source_file, source_checksum)
    )""",
    """CREATE INDEX IF NOT EXISTS ix_engine_v2_batches_recent
        ON engine_v2_batches(started_at_utc DESC)""",
    """CREATE TABLE IF NOT EXISTS engine_v2_watcher_state (
        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
        status TEXT NOT NULL,
        last_cycle_at_utc TEXT,
        last_success_at_utc TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_processed_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS engine_v2_file_observations (
        observation_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        source_version_id TEXT NOT NULL,
        path TEXT NOT NULL,
        signature TEXT NOT NULL,
        status TEXT NOT NULL,
        first_seen_at_utc TEXT NOT NULL,
        last_seen_at_utc TEXT NOT NULL,
        authorized_by TEXT,
        authorized_at_utc TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        UNIQUE(source_id, source_version_id, path)
    )""",
    """CREATE TABLE IF NOT EXISTS engine_v2_file_analyses (
        analysis_id TEXT PRIMARY KEY,
        observation_id TEXT NOT NULL REFERENCES engine_v2_file_observations(observation_id),
        object_template_version_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_version_id TEXT NOT NULL,
        path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_checksum TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL,
        file_modified_at_utc TEXT NOT NULL DEFAULT '',
        source_order INTEGER NOT NULL,
        recognition_status TEXT NOT NULL,
        worksheet_name TEXT NOT NULL DEFAULT '',
        detected_headers_json TEXT NOT NULL DEFAULT '[]',
        required_headers_json TEXT NOT NULL DEFAULT '[]',
        missing_headers_json TEXT NOT NULL DEFAULT '[]',
        unknown_headers_json TEXT NOT NULL DEFAULT '[]',
        checks_json TEXT NOT NULL DEFAULT '{}',
        diagnostics_json TEXT NOT NULL DEFAULT '[]',
        analyzed_at_utc TEXT NOT NULL,
        UNIQUE(source_id, source_version_id, object_template_version_id, path, file_checksum)
    )""",
    """CREATE INDEX IF NOT EXISTS ix_engine_v2_file_analyses_latest
        ON engine_v2_file_analyses(path, analyzed_at_utc DESC)""",
    """CREATE TABLE IF NOT EXISTS engine_v2_evidence (
        evidence_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        row_number INTEGER NOT NULL,
        sheet_name TEXT NOT NULL DEFAULT '',
        source_key TEXT NOT NULL DEFAULT '',
        raw_json TEXT NOT NULL,
        normalized_json TEXT NOT NULL,
        status TEXT NOT NULL,
        diagnostics_json TEXT NOT NULL DEFAULT '[]',
        created_at_utc TEXT NOT NULL,
        FOREIGN KEY(batch_id) REFERENCES engine_v2_batches(batch_id),
        UNIQUE(batch_id, sheet_name, row_number)
    )""",
    """CREATE INDEX IF NOT EXISTS ix_engine_v2_evidence_source_key
        ON engine_v2_evidence(source_key, status)""",
    """CREATE TABLE IF NOT EXISTS engine_v2_objects (
        object_id TEXT PRIMARY KEY,
        object_template_version_id TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        FOREIGN KEY(object_template_version_id)
            REFERENCES employee_template_versions(employee_template_version_id)
    )""",
    """CREATE TABLE IF NOT EXISTS engine_v2_object_evidence (
        object_id TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        link_reason_json TEXT NOT NULL,
        linked_at_utc TEXT NOT NULL,
        PRIMARY KEY(object_id, evidence_id),
        FOREIGN KEY(object_id) REFERENCES engine_v2_objects(object_id),
        FOREIGN KEY(evidence_id) REFERENCES engine_v2_evidence(evidence_id)
    )""",
)


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path), timeout=10, isolation_level="DEFERRED")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_engine_schema(database_path: Path) -> None:
    """Create only engine-v2 tables; never alter legacy schema or rows."""
    if not database_path.is_file():
        raise FileNotFoundError(f"Runtime SQLite database not found: {database_path}")
    connection = connect(database_path)
    try:
        with connection:
            for statement in DDL:
                connection.execute(statement)
            observation_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(engine_v2_file_observations)")
            }
            if "authorized_by" not in observation_columns:
                connection.execute("ALTER TABLE engine_v2_file_observations ADD COLUMN authorized_by TEXT")
            if "authorized_at_utc" not in observation_columns:
                connection.execute("ALTER TABLE engine_v2_file_observations ADD COLUMN authorized_at_utc TEXT")
            batch_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(engine_v2_batches)")
            }
            if "authorized_by" not in batch_columns:
                connection.execute("ALTER TABLE engine_v2_batches ADD COLUMN authorized_by TEXT NOT NULL DEFAULT ''")
            if "authorized_at_utc" not in batch_columns:
                connection.execute("ALTER TABLE engine_v2_batches ADD COLUMN authorized_at_utc TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO engine_v2_schema_migrations(version, applied_at_utc) VALUES (1, datetime('now'))"
            )
            connection.execute(
                "INSERT OR IGNORE INTO engine_v2_schema_migrations(version, applied_at_utc) VALUES (?, datetime('now'))",
                (ENGINE_SCHEMA_VERSION,),
            )
    finally:
        connection.close()
