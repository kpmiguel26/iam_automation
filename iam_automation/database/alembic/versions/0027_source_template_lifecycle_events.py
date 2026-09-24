"""Track repeated report-template removal and restoration events."""

from alembic import op

revision = "0027_source_template_lifecycle_events"
down_revision = "0026_source_template_deletions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_template_lifecycle_events (
            lifecycle_event_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            deleted_by TEXT NOT NULL,
            deleted_at_utc TEXT NOT NULL,
            restored_by TEXT,
            restored_at_utc TEXT
        )"""
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_source_template_lifecycle_active "
        "ON source_template_lifecycle_events(source_id, restored_at_utc, deleted_at_utc DESC)"
    )
    bind.exec_driver_sql(
        """INSERT INTO source_template_lifecycle_events
           (lifecycle_event_id, source_id, deleted_by, deleted_at_utc)
           SELECT lower(hex(randomblob(16))), source_id, deleted_by, deleted_at_utc
           FROM source_template_deletions
           WHERE NOT EXISTS (
               SELECT 1 FROM source_template_lifecycle_events e WHERE e.source_id = source_template_deletions.source_id
           )"""
    )


def downgrade() -> None:
    # Lifecycle events preserve removal/restoration audit history.
    pass
