"""Retain deleted report templates as auditable tombstones."""

from alembic import op

revision = "0026_source_template_deletions"
down_revision = "0025_employee_template_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_template_deletions (
            source_id TEXT PRIMARY KEY,
            deleted_by TEXT NOT NULL,
            deleted_at_utc TEXT NOT NULL
        )"""
    )


def downgrade() -> None:
    # Tombstones are retained as audit evidence during downgrade.
    pass
