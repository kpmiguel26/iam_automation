"""Add indexes used by high-volume source reconciliation."""

from alembic import op


revision = "0010_accessnow_match_indexes"
down_revision = "0009_local_notification_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_worker_identifiers_match "
        "ON worker_identifiers (identifier_type, normalized_value, active, worker_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_workers_canonical_email "
        "ON workers (lower(canonical_email), superseded_by_worker_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_workers_canonical_name "
        "ON workers (lower(first_name), lower(last_name), superseded_by_worker_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_source_checksum "
        "ON ingestion_records (source_system, source_checksum)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    for name in (
        "idx_ingestion_source_checksum",
        "idx_workers_canonical_name",
        "idx_workers_canonical_email",
        "idx_worker_identifiers_match",
    ):
        bind.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")
