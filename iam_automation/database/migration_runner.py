"""
File: iam_automation/database/migration_runner.py
Purpose: Supports runtime database initialization, schema, or migration operations.
Responsibilities: Exposes or coordinates: _alembic_config, _legacy_versions, _current_revision, _legacy_version_for_revision, apply_pending_migrations, applied_migrations, ….
Dependencies: alembic, sqlalchemy
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


_REVISION_TO_LEGACY_VERSION = {
    "0001_baseline": "v001_initial_schema",
    "0002_notification_indexes": "v002_notification_indexes",
    "0003_ingestion_records": "v003_ingestion_records",
    "0004_worker_domain": "v004_worker_domain",
    "0005_rsr_worker_details": "v005_rsr_worker_details",
    "0006_worker_history": "v006_worker_history",
    "0007_source_observations": "v007_source_observations",
    "0008_source_file_timestamps": "v008_source_file_timestamps",
    "0009_local_notification_store": "v009_local_notification_store",
    "0010_accessnow_match_indexes": "v010_accessnow_match_indexes",
    "0011_business_rules": "v011_business_rules",
    "0012_compact_employee_fields": "v012_compact_employee_fields",
    "0013_star_schema": "v013_star_schema",
    "0014_worker_field_history": "v014_worker_field_history",
    "0015_source_separated_write_model": "v015_source_separated_write_model",
    "0016_allow_fact_linking": "v016_allow_fact_linking",
}
_LEGACY_TO_REVISION = {value: key for key, value in _REVISION_TO_LEGACY_VERSION.items()}


def _alembic_config(connection) -> Config:
    config_path = Path(__file__).with_name("alembic.ini")
    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.with_name("alembic")))
    config.attributes["connection"] = connection
    return config


def _legacy_versions(database_path: Path) -> tuple[str, ...]:
    connection = sqlite3.connect(database_path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if not exists:
            return ()
        return tuple(row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version"))
    finally:
        connection.close()


def _current_revision(connection) -> str | None:
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    ).first()
    if not exists:
        return None
    row = connection.exec_driver_sql("SELECT version_num FROM alembic_version ORDER BY version_num DESC").first()
    return str(row[0]) if row else None


def _legacy_version_for_revision(revision: str | None) -> tuple[str, ...]:
    if revision == "0002_notification_indexes":
        return ("v001_initial_schema", "v002_notification_indexes")
    if revision == "0003_ingestion_records":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records")
    if revision == "0004_worker_domain":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain")
    if revision == "0005_rsr_worker_details":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details")
    if revision == "0006_worker_history":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history")
    if revision == "0007_source_observations":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations")
    if revision == "0008_source_file_timestamps":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations", "v008_source_file_timestamps")
    if revision == "0009_local_notification_store":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations", "v008_source_file_timestamps", "v009_local_notification_store")
    if revision == "0010_accessnow_match_indexes":
        return ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations", "v008_source_file_timestamps", "v009_local_notification_store", "v010_accessnow_match_indexes")
    if revision == "0011_business_rules":
        return (*_legacy_version_for_revision("0010_accessnow_match_indexes"), "v011_business_rules")
    if revision == "0012_compact_employee_fields":
        return (*_legacy_version_for_revision("0011_business_rules"), "v012_compact_employee_fields")
    if revision == "0013_star_schema":
        return (*_legacy_version_for_revision("0012_compact_employee_fields"), "v013_star_schema")
    if revision == "0014_worker_field_history":
        return (*_legacy_version_for_revision("0013_star_schema"), "v014_worker_field_history")
    if revision == "0015_source_separated_write_model":
        return (*_legacy_version_for_revision("0014_worker_field_history"), "v015_source_separated_write_model")
    if revision == "0016_allow_fact_linking":
        return (*_legacy_version_for_revision("0015_source_separated_write_model"), "v016_allow_fact_linking")
    if revision == "0001_baseline":
        return ("v001_initial_schema",)
    return ()


def apply_pending_migrations(database_path: Path, actor: str = "system") -> tuple[str, ...]:
    """Upgrade a runtime SQLite database to the current Alembic head.

    Databases created by the original runner are stamped at their equivalent
    Alembic revision without replaying DDL. This preserves existing data while
    moving schema ownership to the standard SQLAlchemy migration tool.
    """
    del actor  # Alembic owns revision state; audit actors remain application-level data.
    path = database_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    try:
        with engine.connect() as connection:
            before = _current_revision(connection)
            if before is None:
                legacy = set(_legacy_versions(path))
                config = _alembic_config(connection)
                legacy_revision = next(
                    (
                        revision
                        for revision in reversed(tuple(_REVISION_TO_LEGACY_VERSION))
                        if _REVISION_TO_LEGACY_VERSION[revision] in legacy
                    ),
                    None,
                )
                if legacy_revision:
                    # The original runner recorded legacy versions without an
                    # Alembic head. Stamp the newest known legacy version, then
                    # actually execute every newer migration (including v006).
                    command.stamp(config, legacy_revision)
                    command.upgrade(config, "head")
                else:
                    command.upgrade(config, "head")
            else:
                command.upgrade(_alembic_config(connection), "head")
            connection.commit()
            after = _current_revision(connection)
    finally:
        engine.dispose()

    before_versions = set(_legacy_version_for_revision(before))
    after_versions = _legacy_version_for_revision(after)
    return tuple(version for version in after_versions if version not in before_versions)


def applied_migrations(database_path: Path) -> tuple[str, ...]:
    path = database_path.expanduser().resolve()
    if not path.is_file():
        return ()
    legacy = _legacy_versions(path)
    if legacy:
        return legacy
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    try:
        with engine.connect() as connection:
            return _legacy_version_for_revision(_current_revision(connection))
    finally:
        engine.dispose()


def current_database_revision(database_path: Path) -> str | None:
    """Return the Alembic schema revision currently stored in SQLite."""
    path = database_path.expanduser().resolve()
    if not path.is_file():
        return None
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    try:
        with engine.connect() as connection:
            return _current_revision(connection)
    finally:
        engine.dispose()
#endfile
