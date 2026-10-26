"""Record configuration validation against an immutable report-template version."""

from alembic import op


revision = "0029_source_template_validation"
down_revision = "0028_source_template_cascade_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_template_validation_events (
            validation_event_id TEXT PRIMARY KEY,
            definition_version_id TEXT NOT NULL
                REFERENCES source_definition_versions(definition_version_id),
            content_sha256 TEXT NOT NULL,
            validated_by TEXT NOT NULL,
            validated_at_utc TEXT NOT NULL
        )"""
    )
    op.get_bind().exec_driver_sql(
        """CREATE INDEX IF NOT EXISTS ix_source_template_validation_version_hash
           ON source_template_validation_events(definition_version_id, content_sha256)"""
    )


def downgrade() -> None:
    # Validation audit events remain as governance evidence during downgrade.
    pass
