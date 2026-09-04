"""Add relational history for legacy worker profile snapshots."""

from alembic import op


revision = "0014_worker_field_history"
down_revision = "0013_star_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS fact_worker_field_history (
            history_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            source_system TEXT NOT NULL DEFAULT 'CANONICAL',
            field_key TEXT NOT NULL,
            value_text TEXT NOT NULL DEFAULT '',
            version_number INTEGER NOT NULL DEFAULT 1,
            observed_at_utc TEXT NOT NULL DEFAULT '',
            source_file TEXT NOT NULL DEFAULT '',
            UNIQUE(worker_id, source_system, field_key, version_number)
        )"""
    )
    op.get_bind().exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_star_history_worker ON fact_worker_field_history(worker_id, field_key, version_number)")


def downgrade() -> None:
    pass
