"""
File: iam_automation/database/alembic/versions/0007_source_observations.py
Purpose: Add source observation lifecycle and worker source profiles.
Responsibilities: Exposes or coordinates: upgrade, downgrade.
Dependencies: alembic
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from alembic import op


revision = "0007_source_observations"
down_revision = "0006_worker_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(ingestion_records)")}
    for name, definition in (
        ("observation_state", "TEXT NOT NULL DEFAULT 'PENDING'"),
        ("superseded_by_record_id", "TEXT"),
        ("linked_at_utc", "TEXT"),
        ("last_seen_at_utc", "TEXT"),
    ):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE ingestion_records ADD COLUMN {name} {definition}")

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS worker_source_profiles (
            profile_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            source_system TEXT NOT NULL,
            source_record_key TEXT NOT NULL,
            current_record_id TEXT,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'CURRENT',
            first_seen_at_utc TEXT NOT NULL DEFAULT '',
            last_seen_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(source_system, source_record_key)
        )"""
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ingestion_observation_state ON ingestion_records (source_system, observation_state, created_at_utc)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_source_profiles_worker ON worker_source_profiles (worker_id, source_system)")
    connection.exec_driver_sql(
        """UPDATE ingestion_records
           SET observation_state = CASE
               WHEN status IN ('APPLIED', 'LINKED', 'CURRENT') AND matched_worker_id IS NOT NULL THEN 'CURRENT'
               WHEN status = 'SUPERSEDED' THEN 'SUPERSEDED'
               ELSE 'PENDING'
           END
           WHERE observation_state IS NULL OR observation_state = '' OR observation_state = 'PENDING'"""
    )


def downgrade() -> None:
    # Additive SQLite migration; historical evidence is intentionally retained.
    pass
