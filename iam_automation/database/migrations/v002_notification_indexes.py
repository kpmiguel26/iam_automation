"""
File: iam_automation/database/migrations/v002_notification_indexes.py
Purpose: Indexes for notification queries used by the application shell.
Responsibilities: Exposes or coordinates: upgrade.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""


VERSION = "v002_notification_indexes"
DESCRIPTION = "Index notification recipient and status lookups."


def upgrade(connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_status "
        "ON notifications (recipient_username, status, created_at_utc)"
    )
#endfile
