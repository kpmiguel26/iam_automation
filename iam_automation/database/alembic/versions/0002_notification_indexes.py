"""
File: iam_automation/database/alembic/versions/0002_notification_indexes.py
Purpose: Add indexes used by notification queries.
Responsibilities: Exposes or coordinates: upgrade, downgrade.
Dependencies: alembic
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from alembic import op


revision = "0002_notification_indexes"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_status "
        "ON notifications (recipient_username, status, created_at_utc)"
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_recipient_status", table_name="notifications")
#endfile
