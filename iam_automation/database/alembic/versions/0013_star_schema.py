"""Create the clean-start star-schema tables for the testing runtime."""

from alembic import op


revision = "0013_star_schema"
down_revision = "0012_compact_employee_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS dim_source (source_id TEXT PRIMARY KEY, source_system TEXT NOT NULL UNIQUE, label TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1)")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS dim_field (field_id TEXT PRIMARY KEY, field_key TEXT NOT NULL UNIQUE, label TEXT NOT NULL DEFAULT '', data_type TEXT NOT NULL DEFAULT 'TEXT', sensitivity TEXT NOT NULL DEFAULT 'INTERNAL', reportable INTEGER NOT NULL DEFAULT 1, rule_enabled INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1)")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS dim_date (date_key INTEGER PRIMARY KEY, calendar_date TEXT NOT NULL UNIQUE, year INTEGER NOT NULL, month INTEGER NOT NULL, day INTEGER NOT NULL, day_of_week INTEGER NOT NULL, is_weekend INTEGER NOT NULL DEFAULT 0)")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS dim_vendor (vendor_id TEXT PRIMARY KEY, vendor_name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS fact_source_snapshot (snapshot_id TEXT PRIMARY KEY, worker_id TEXT REFERENCES workers(worker_id), batch_id TEXT NOT NULL REFERENCES import_batches(batch_id), source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_key TEXT NOT NULL, observed_at_utc TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'CURRENT', retention_rank INTEGER NOT NULL DEFAULT 1, UNIQUE(batch_id, source_id, source_record_key))")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS fact_worker_field (field_value_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES fact_source_snapshot(snapshot_id), worker_id TEXT REFERENCES workers(worker_id), field_id TEXT NOT NULL REFERENCES dim_field(field_id), value_text TEXT NOT NULL DEFAULT '', UNIQUE(snapshot_id, field_id))")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS fact_termination (termination_id TEXT PRIMARY KEY, snapshot_id TEXT REFERENCES fact_source_snapshot(snapshot_id), worker_id TEXT REFERENCES workers(worker_id), date_key INTEGER REFERENCES dim_date(date_key), termination_date TEXT NOT NULL DEFAULT '', termination_type TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ACTIVE')")
    bind.exec_driver_sql("CREATE TABLE IF NOT EXISTS fact_assignment (assignment_id TEXT PRIMARY KEY, snapshot_id TEXT REFERENCES fact_source_snapshot(snapshot_id), worker_id TEXT REFERENCES workers(worker_id), vendor_id TEXT REFERENCES dim_vendor(vendor_id), work_order_id TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '', supervisor_name TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ACTIVE')")
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_star_snapshot_worker ON fact_source_snapshot(worker_id, source_id, observed_at_utc)",
        "CREATE INDEX IF NOT EXISTS idx_star_snapshot_batch ON fact_source_snapshot(batch_id, retention_rank)",
        "CREATE INDEX IF NOT EXISTS idx_star_field_worker ON fact_worker_field(worker_id, field_id)",
        "CREATE INDEX IF NOT EXISTS idx_star_termination_worker ON fact_termination(worker_id, termination_date)",
        "CREATE INDEX IF NOT EXISTS idx_star_assignment_worker ON fact_assignment(worker_id, vendor_id)",
    ):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    # Star data is testing evidence; removal requires an explicit decision.
    pass
