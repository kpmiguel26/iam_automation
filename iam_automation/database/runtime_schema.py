from __future__ import annotations

import sqlite3
from pathlib import Path


RUNTIME_SCHEMA_VERSION = "1.0.0"


def initialize_runtime_database(path: Path) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS app_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approved_users (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS app_users (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS roles (
                role_name TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS user_roles (
                username TEXT NOT NULL,
                role_name TEXT NOT NULL,
                PRIMARY KEY (username, role_name)
            );
            CREATE TABLE IF NOT EXISTS admin_delegations (
                delegation_id TEXT PRIMARY KEY,
                principal_username TEXT NOT NULL,
                delegate_username TEXT NOT NULL,
                scope TEXT NOT NULL,
                starts_at_utc TEXT NOT NULL,
                expires_at_utc TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_by TEXT NOT NULL,
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                revoked_at_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS approval_assignments (
                assignment_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                assigned_to TEXT NOT NULL,
                assigned_by TEXT NOT NULL,
                assigned_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_requests (
                request_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                created_by TEXT NOT NULL,
                computer_name TEXT NOT NULL,
                application_version TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                expected_record_version INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                assigned_to TEXT,
                reviewed_by TEXT,
                review_note TEXT,
                updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_change_requests_queue
                ON change_requests (status, assigned_to, created_at_utc);
            CREATE TABLE IF NOT EXISTS publication_queue (
                publication_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'PENDING_PUBLICATION',
                queued_by TEXT NOT NULL,
                queued_at_utc TEXT NOT NULL,
                processed_at_utc TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                recipient_username TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'INFO',
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                target_route TEXT NOT NULL DEFAULT '',
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                read_at_utc TEXT,
                expires_at_utc TEXT,
                status TEXT NOT NULL DEFAULT 'UNREAD'
            );
            CREATE TABLE IF NOT EXISTS import_batches (
                batch_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'COMPLETED_WITH_WARNINGS',
                total_rows INTEGER NOT NULL DEFAULT 0,
                valid_rows INTEGER NOT NULL DEFAULT 0,
                quarantine_rows INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL,
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at_utc TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS quarantine_records (
                quarantine_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                reason TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_by TEXT,
                resolved_at_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS session_revocations (
                revocation_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                revoked_by TEXT NOT NULL,
                revoked_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
                reason TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_recipient_status
                ON notifications (recipient_username, status, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_admin_delegations_active
                ON admin_delegations (delegate_username, status, expires_at_utc);
            CREATE TABLE IF NOT EXISTS template_mappings (
                mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_name TEXT NOT NULL,
                template_name TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS system_profiles (
                profile_name TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO app_metadata (metadata_key, metadata_value, updated_at_utc)
            VALUES ('schema_version', '1.0.0', datetime('now'))
            ON CONFLICT(metadata_key) DO NOTHING;
            INSERT OR IGNORE INTO roles (role_name, description, active) VALUES
                ('REQUESTER', 'Creates and tracks requests', 1),
                ('REVIEWER', 'Reviews and decides requests', 1),
                ('WRITER', 'Applies approved changes and publishes', 1),
                ('AUDITOR', 'Reads and exports evidence', 1),
                ('APPLICATION_ADMIN', 'Operates the application', 1),
                ('MASTER_ADMIN', 'Controls security and recovery', 1),
                ('ADMINISTRATOR', 'Compatibility alias for APPLICATION_ADMIN', 1);
            """
        )
        notification_columns = {row[1] for row in connection.execute("PRAGMA table_info(notifications)")}
        for column, definition in (("entity_type", "TEXT NOT NULL DEFAULT ''"), ("entity_id", "TEXT NOT NULL DEFAULT ''"), ("expires_at_utc", "TEXT")):
            if column not in notification_columns:
                connection.execute(f"ALTER TABLE notifications ADD COLUMN {column} {definition}")
        app_user_columns = {row[1] for row in connection.execute("PRAGMA table_info(app_users)")}
        if "status" not in app_user_columns:
            connection.execute("ALTER TABLE app_users ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
        connection.execute("UPDATE app_users SET status = CASE WHEN active = 1 THEN 'ACTIVE' ELSE 'INACTIVE' END WHERE status IS NULL OR status = ''")
        connection.commit()
    finally:
        connection.close()
    return path
