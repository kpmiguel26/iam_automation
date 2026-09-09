"""Bind rule versions to the rule context used for evaluation."""

from alembic import op


revision = "0020_rule_context_binding"
down_revision = "0019_rule_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(business_rule_versions)")}
    if "context_version_id" not in columns:
        bind.exec_driver_sql(
            "ALTER TABLE business_rule_versions ADD COLUMN context_version_id TEXT REFERENCES rule_context_versions(context_version_id)"
        )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_business_rule_versions_context ON business_rule_versions(context_version_id)"
    )


def downgrade() -> None:
    # Rule history is retained; the nullable binding is harmless on rollback.
    pass
