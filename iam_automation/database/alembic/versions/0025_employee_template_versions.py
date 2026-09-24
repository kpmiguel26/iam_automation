"""Persist versioned employee-template field selections."""

from alembic import op

revision = "0025_employee_template_versions"
down_revision = "0024_source_ingestion_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS employee_template_versions (
            employee_template_version_id TEXT PRIMARY KEY,
            template_key TEXT NOT NULL,
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'APPROVED')),
            definition_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            UNIQUE(template_key, version_number)
        )"""
    )
    op.get_bind().exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_employee_template_versions_latest "
        "ON employee_template_versions(template_key, version_number DESC)"
    )


def downgrade() -> None:
    # Template snapshots are retained as configuration evidence during downgrade.
    pass
