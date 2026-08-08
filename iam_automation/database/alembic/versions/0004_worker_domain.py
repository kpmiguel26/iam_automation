"""
File: iam_automation/database/alembic/versions/0004_worker_domain.py
Purpose: Add canonical worker identity and source lineage tables.
Responsibilities: Exposes or coordinates: upgrade, downgrade.
Dependencies: alembic
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from alembic import op


revision = "0004_worker_domain"
down_revision = "0003_ingestion_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS workers (
        worker_id TEXT PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
        display_name TEXT NOT NULL DEFAULT '', canonical_email TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'PENDING',
        record_version INTEGER NOT NULL DEFAULT 1, created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS worker_identifiers (
        identifier_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, source_system TEXT NOT NULL,
        identifier_type TEXT NOT NULL, identifier_value TEXT NOT NULL, normalized_value TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, confidence TEXT NOT NULL DEFAULT 'HIGH', valid_from_utc TEXT,
        valid_to_utc TEXT, created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (source_system, identifier_type, normalized_value)
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_worker_identifiers_worker ON worker_identifiers (worker_id)")
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS worker_engagements (
        engagement_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, vendor_name TEXT NOT NULL DEFAULT '',
        program TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '', lob TEXT NOT NULL DEFAULT '',
        supervisor_name TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',
        site_location TEXT NOT NULL DEFAULT '', onboarding_date TEXT NOT NULL DEFAULT '', production_start_date TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'PENDING', npn TEXT NOT NULL DEFAULT '', license_state TEXT NOT NULL DEFAULT '',
        license_number TEXT NOT NULL DEFAULT '', taxonomy_code TEXT NOT NULL DEFAULT '', key_billable_function TEXT NOT NULL DEFAULT '',
        source_system TEXT NOT NULL DEFAULT '', created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_worker_engagements_worker ON worker_engagements (worker_id)")
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS worker_source_lineage (
        lineage_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, engagement_id TEXT, batch_id TEXT NOT NULL,
        source_system TEXT NOT NULL, source_file TEXT NOT NULL, source_checksum TEXT NOT NULL, row_number INTEGER NOT NULL,
        field_name TEXT NOT NULL, raw_value TEXT NOT NULL DEFAULT '', normalized_value TEXT NOT NULL DEFAULT '',
        observed_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_worker_lineage_worker ON worker_source_lineage (worker_id, field_name, observed_at_utc)")
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS worker_discrepancies (
        discrepancy_id TEXT PRIMARY KEY, worker_id TEXT, source_system TEXT NOT NULL, source_record_key TEXT NOT NULL,
        field_name TEXT NOT NULL, current_value TEXT NOT NULL DEFAULT '', incoming_value TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'OPEN', resolution TEXT, created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_by TEXT, resolved_at_utc TEXT
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_worker_discrepancies_status ON worker_discrepancies (status, created_at_utc)")


def downgrade() -> None:
    op.drop_index("idx_worker_discrepancies_status", table_name="worker_discrepancies")
    op.drop_table("worker_discrepancies")
    op.drop_index("idx_worker_lineage_worker", table_name="worker_source_lineage")
    op.drop_table("worker_source_lineage")
    op.drop_index("idx_worker_engagements_worker", table_name="worker_engagements")
    op.drop_table("worker_engagements")
    op.drop_index("idx_worker_identifiers_worker", table_name="worker_identifiers")
    op.drop_table("worker_identifiers")
    op.drop_table("workers")
