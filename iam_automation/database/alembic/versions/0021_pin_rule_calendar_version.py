"""Pin each rule context version to an immutable calendar version."""

from alembic import op


revision = "0021_pin_rule_calendar_version"
down_revision = "0020_rule_context_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(rule_context_versions)")}
    if "default_calendar_version_id" not in columns:
        bind.exec_driver_sql(
            "ALTER TABLE rule_context_versions ADD COLUMN default_calendar_version_id TEXT REFERENCES rule_calendar_versions(calendar_version_id)"
        )

    # Existing context versions were historically linked only to a calendar
    # identity. Pin them to the calendar version that was current at migration
    # time so future calendar edits cannot silently reinterpret their rules.
    bind.exec_driver_sql(
        """
        UPDATE rule_context_versions
        SET default_calendar_version_id = (
            SELECT version.calendar_version_id
            FROM rule_calendar_versions AS version
            JOIN rule_calendars AS calendar ON calendar.calendar_id = version.calendar_id
            WHERE version.calendar_id = rule_context_versions.default_calendar_id
              AND version.version = calendar.current_version
        )
        WHERE default_calendar_version_id IS NULL
        """
    )
    # Rule versions created before context binding had a NULL context. Bind
    # those historical definitions to the context that was current at the
    # migration boundary instead of letting future context edits affect them.
    bind.exec_driver_sql(
        """
        UPDATE business_rule_versions
        SET context_version_id = (
            SELECT context_version.context_version_id
            FROM rule_context_versions AS context_version
            JOIN rule_contexts AS context ON context.context_id = context_version.context_id
            WHERE context.context_key = 'DEFAULT'
              AND context_version.version = context.current_version
        )
        WHERE context_version_id IS NULL
        """
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_rule_context_versions_calendar_version ON rule_context_versions(default_calendar_version_id)"
    )


def downgrade() -> None:
    # Keep the binding on rollback to avoid reinterpreting historical rules.
    pass
