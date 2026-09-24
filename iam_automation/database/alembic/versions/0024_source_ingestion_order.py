"""Store template ingestion order independently from immutable versions."""

from alembic import op

revision = "0024_source_ingestion_order"
down_revision = "0023_ingestion_source_definition_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_ingestion_orders (
            source_id TEXT PRIMARY KEY,
            ingestion_order INTEGER NOT NULL CHECK (ingestion_order > 0),
            updated_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )"""
    )


def downgrade() -> None:
    # Order metadata is retained as configuration evidence during downgrade.
    pass
