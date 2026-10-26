"""Record retained-data impact for report-template removals."""

from alembic import op


revision = "0028_source_template_cascade_audit"
down_revision = "0027_source_template_lifecycle_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(source_template_lifecycle_events)")}
    if "removal_impact_json" not in columns:
        bind.exec_driver_sql(
            "ALTER TABLE source_template_lifecycle_events "
            "ADD COLUMN removal_impact_json TEXT NOT NULL DEFAULT '{}'"
        )


def downgrade() -> None:
    # Removal impact is audit evidence and is retained on downgrade.
    pass
