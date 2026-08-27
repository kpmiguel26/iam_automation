"""Persist source workbook modification times for portable chronological imports."""

from alembic import op


revision = "0008_source_file_timestamps"
down_revision = "0007_source_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(import_batches)")}
    if "source_modified_at_utc" not in columns:
        connection.exec_driver_sql("ALTER TABLE import_batches ADD COLUMN source_modified_at_utc TEXT NOT NULL DEFAULT ''")
    connection.exec_driver_sql(
        "UPDATE import_batches SET source_modified_at_utc = created_at_utc "
        "WHERE source_modified_at_utc IS NULL OR source_modified_at_utc = ''"
    )


def downgrade() -> None:
    # SQLite migration is additive; the timestamp remains part of historical evidence.
    pass
