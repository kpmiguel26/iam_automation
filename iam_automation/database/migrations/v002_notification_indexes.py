"""Indexes for notification queries used by the application shell."""


VERSION = "v002_notification_indexes"
DESCRIPTION = "Index notification recipient and status lookups."


def upgrade(connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_status "
        "ON notifications (recipient_username, status, created_at_utc)"
    )
