"""Add versioned rule context, calendars and field metadata."""

from alembic import op


revision = "0019_rule_configuration"
down_revision = "0018_fact_quarantine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_calendars (
            calendar_id TEXT PRIMARY KEY,
            calendar_key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT ''
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_calendar_versions (
            calendar_version_id TEXT PRIMARY KEY,
            calendar_id TEXT NOT NULL REFERENCES rule_calendars(calendar_id),
            version INTEGER NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            operating_weekdays_json TEXT NOT NULL DEFAULT '[0,1,2,3,4]',
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(calendar_id, version)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_calendar_holidays (
            holiday_id TEXT PRIMARY KEY,
            calendar_version_id TEXT NOT NULL REFERENCES rule_calendar_versions(calendar_version_id),
            holiday_date TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            recurring_annually INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            source_country TEXT NOT NULL DEFAULT '',
            source_year INTEGER,
            holiday_type TEXT NOT NULL DEFAULT '',
            observed_date TEXT,
            UNIQUE(calendar_version_id, holiday_date, label)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_contexts (
            context_id TEXT PRIMARY KEY,
            context_key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT ''
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_context_versions (
            context_version_id TEXT PRIMARY KEY,
            context_id TEXT NOT NULL REFERENCES rule_contexts(context_id),
            version INTEGER NOT NULL,
            default_calendar_id TEXT NOT NULL REFERENCES rule_calendars(calendar_id),
            timezone TEXT NOT NULL DEFAULT 'UTC',
            missing_data_behavior TEXT NOT NULL DEFAULT 'FINDING',
            date_boundary TEXT NOT NULL DEFAULT 'EXCLUSIVE_START_INCLUSIVE_END',
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(context_id, version)
        )"""
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_rule_calendar_versions_current ON rule_calendar_versions(calendar_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_rule_calendar_holidays_date ON rule_calendar_holidays(calendar_version_id, holiday_date)",
        "CREATE INDEX IF NOT EXISTS idx_rule_context_versions_current ON rule_context_versions(context_id, version)",
    ):
        bind.exec_driver_sql(statement)

    # Field metadata is configuration for evaluation and reporting only. The
    # existing star-schema and source mapping contracts remain unchanged.
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(dim_field)")}
    for column, definition in (
        ("semantic_type", "TEXT NOT NULL DEFAULT 'TEXT'"),
        ("nullable", "INTEGER NOT NULL DEFAULT 1"),
        ("allowed_operators_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("normalization_name", "TEXT NOT NULL DEFAULT 'identity'"),
        ("metadata_version", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_by", "TEXT NOT NULL DEFAULT 'system'"),
        ("updated_at_utc", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in columns:
            bind.exec_driver_sql(f"ALTER TABLE dim_field ADD COLUMN {column} {definition}")
    holiday_columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(rule_calendar_holidays)")}
    for column, definition in (
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("source", "TEXT NOT NULL DEFAULT 'MANUAL'"),
        ("source_country", "TEXT NOT NULL DEFAULT ''"),
        ("source_year", "INTEGER"),
        ("holiday_type", "TEXT NOT NULL DEFAULT ''"),
        ("observed_date", "TEXT"),
    ):
        if column not in holiday_columns:
            bind.exec_driver_sql(f"ALTER TABLE rule_calendar_holidays ADD COLUMN {column} {definition}")
    bind.exec_driver_sql(
        "UPDATE dim_field SET semantic_type = CASE WHEN data_type IS NULL OR data_type = '' THEN 'TEXT' ELSE UPPER(data_type) END"
    )

    # A default context makes the configuration page immediately useful while
    # keeping later calendars and contexts additive and versioned.
    bind.exec_driver_sql(
        """INSERT OR IGNORE INTO rule_calendars
            (calendar_id, calendar_key, label, current_version, active, created_by, created_at_utc, updated_at_utc)
            VALUES ('calendar:standard', 'STANDARD', 'Standard operating calendar', 1, 1, 'system', datetime('now'), datetime('now'))"""
    )
    bind.exec_driver_sql(
        """INSERT OR IGNORE INTO rule_calendar_versions
            (calendar_version_id, calendar_id, version, timezone, operating_weekdays_json, created_by, created_at_utc)
            VALUES ('calendar:standard:1', 'calendar:standard', 1, 'UTC', '[0,1,2,3,4]', 'system', datetime('now'))"""
    )
    bind.exec_driver_sql(
        """INSERT OR IGNORE INTO rule_contexts
            (context_id, context_key, label, current_version, active, created_by, created_at_utc, updated_at_utc)
            VALUES ('context:default', 'DEFAULT', 'Default rule context', 1, 1, 'system', datetime('now'), datetime('now'))"""
    )
    bind.exec_driver_sql(
        """INSERT OR IGNORE INTO rule_context_versions
            (context_version_id, context_id, version, default_calendar_id, timezone, missing_data_behavior, date_boundary, created_by, created_at_utc)
            VALUES ('context:default:1', 'context:default', 1, 'calendar:standard', 'UTC', 'FINDING', 'EXCLUSIVE_START_INCLUSIVE_END', 'system', datetime('now'))"""
    )


def downgrade() -> None:
    # Configuration history is intentionally retained during the transition.
    pass
