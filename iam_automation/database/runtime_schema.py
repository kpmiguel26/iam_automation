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
            """
        )
        connection.commit()
    finally:
        connection.close()
    return path
