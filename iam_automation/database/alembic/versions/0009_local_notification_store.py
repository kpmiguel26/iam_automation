"""Retire notification records from the runtime database."""

from alembic import op


revision = "0009_local_notification_store"
down_revision = "0008_source_file_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Notifications now live in the local .iam_notifications file store. Keep
    # the legacy table for old schema compatibility, but do not retain rows.
    op.get_bind().exec_driver_sql("DELETE FROM notifications")


def downgrade() -> None:
    # Notification rows cannot be reconstructed from the local file store.
    pass
