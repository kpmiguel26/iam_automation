"""Persist versioned ingestion templates independently from runtime activation."""

from alembic import op

revision = "0023_ingestion_source_definition_versions"
down_revision = "0022_source_rule_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_definition_versions (
            definition_version_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            status TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED')),
            definition_json TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            approved_by TEXT,
            approved_at_utc TEXT,
            UNIQUE (source_id, version_number)
        )"""
    )
    op.get_bind().exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_source_definition_versions_status ON source_definition_versions(status, updated_at_utc DESC)"
    )


def downgrade() -> None:
    # Saved templates are governance records; retain them during downgrade.
    pass
