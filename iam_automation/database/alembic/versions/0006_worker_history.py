"""Add immutable worker history and duplicate merge events."""

from alembic import op


revision = "0006_worker_history"
down_revision = "0005_rsr_worker_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    worker_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(workers)")}
    if "superseded_by_worker_id" not in worker_columns:
        connection.exec_driver_sql("ALTER TABLE workers ADD COLUMN superseded_by_worker_id TEXT")
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS worker_profile_versions (
            version_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            version_number INTEGER NOT NULL,
            change_type TEXT NOT NULL DEFAULT 'SOURCE_IMPORT',
            snapshot_json TEXT NOT NULL,
            changed_fields_json TEXT NOT NULL DEFAULT '[]',
            source_system TEXT NOT NULL DEFAULT '',
            source_file TEXT NOT NULL DEFAULT '',
            source_checksum TEXT NOT NULL DEFAULT '',
            source_record_key TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(worker_id, version_number)
        )"""
    )
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS worker_merge_events (
            merge_id TEXT PRIMARY KEY,
            survivor_worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            duplicate_worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            reason TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT ''
        )"""
    )


def downgrade() -> None:
    # Additive SQLite migration. Historical evidence is never removed.
    pass
