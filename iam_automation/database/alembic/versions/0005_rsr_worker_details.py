"""
File: iam_automation/database/alembic/versions/0005_rsr_worker_details.py
Purpose: Add RSR matching metadata and engagement enrichment fields.
Responsibilities: Exposes or coordinates: upgrade, downgrade.
Dependencies: alembic
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from alembic import op


revision = "0005_rsr_worker_details"
down_revision = "0004_worker_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(ingestion_records)")}
    for name, definition in (("match_status", "TEXT NOT NULL DEFAULT 'NOT_EVALUATED'"), ("matched_worker_id", "TEXT"), ("match_reason", "TEXT NOT NULL DEFAULT ''")):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE ingestion_records ADD COLUMN {name} {definition}")
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(worker_engagements)")}
    for name, definition in (("statement_of_work", "TEXT NOT NULL DEFAULT ''"), ("work_order_id", "TEXT NOT NULL DEFAULT ''"), ("primary_contact_name", "TEXT NOT NULL DEFAULT ''")):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE worker_engagements ADD COLUMN {name} {definition}")


def downgrade() -> None:
    # Additive SQLite migration; columns are intentionally retained on downgrade.
    pass
