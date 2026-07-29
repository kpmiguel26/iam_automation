"""Add indexes used by notification queries."""

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
