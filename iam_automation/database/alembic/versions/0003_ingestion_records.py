"""Add source staging records for automated ingestion."""

from alembic import op


revision = "0003_ingestion_records"
down_revision = "0002_notification_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Runtime bootstrap creates the current schema before Alembic runs. The
    # IF NOT EXISTS form keeps both fresh and legacy databases idempotent.
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS ingestion_records (
            record_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            source_system TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_checksum TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            source_record_key TEXT NOT NULL,
            normalized_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'STAGED',
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (source_file, source_checksum, row_number)
        )"""
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ingestion_records_source_key ON ingestion_records (source_system, source_record_key, created_at_utc)")


def downgrade() -> None:
    op.drop_index("idx_ingestion_records_source_key", table_name="ingestion_records")
    op.drop_table("ingestion_records")
