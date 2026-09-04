"""Add governed compact employee field projections."""

from alembic import op


revision = "0012_compact_employee_fields"
down_revision = "0011_business_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS field_catalog (
            field_key TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            data_type TEXT NOT NULL DEFAULT 'TEXT',
            sensitivity TEXT NOT NULL DEFAULT 'INTERNAL',
            reportable INTEGER NOT NULL DEFAULT 1,
            rule_enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT ''
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS employee_field_values (
            value_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL REFERENCES workers(worker_id),
            source_system TEXT NOT NULL,
            field_key TEXT NOT NULL REFERENCES field_catalog(field_key),
            value_text TEXT NOT NULL DEFAULT '',
            source_record_key TEXT NOT NULL DEFAULT '',
            source_record_id TEXT NOT NULL DEFAULT '',
            observed_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(worker_id, source_system, field_key)
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_employee_field_worker ON employee_field_values (worker_id, field_key)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_employee_field_source ON employee_field_values (source_system, field_key)")


def downgrade() -> None:
    # Keep the pilot tables recoverable; removal requires an explicit data-retention decision.
    pass
