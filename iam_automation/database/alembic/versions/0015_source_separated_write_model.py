"""Create the source-separated star-schema write model."""

from alembic import op


revision = "0015_source_separated_write_model"
down_revision = "0014_worker_field_history"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}
    if column not in columns:
        bind.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade() -> None:
    bind = op.get_bind()
    _add_column_if_missing("import_batches", "filtered_rows", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("import_batches", "termination_window_start", "TEXT")

    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS dim_employee (
            employee_key TEXT PRIMARY KEY,
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            canonical_email TEXT NOT NULL DEFAULT '',
            record_version INTEGER NOT NULL DEFAULT 1,
            superseded_by_employee_key TEXT,
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (superseded_by_employee_key) REFERENCES dim_employee(employee_key)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS bridge_employee_identifier (
            employee_identifier_key TEXT PRIMARY KEY,
            employee_key TEXT NOT NULL REFERENCES dim_employee(employee_key),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id),
            source_system TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            source_record_id TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            confidence TEXT NOT NULL DEFAULT 'HIGH',
            valid_from_utc TEXT,
            valid_to_utc TEXT,
            created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(source_system, identifier_type, normalized_value)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS source_field_mapping (
            mapping_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES dim_source(source_id),
            source_field_key TEXT NOT NULL,
            field_id TEXT REFERENCES dim_field(field_id),
            target_kind TEXT NOT NULL DEFAULT 'FACT' CHECK(target_kind IN ('DIMENSION', 'FACT', 'IDENTIFIER', 'STATUS', 'IGNORE')),
            transform_name TEXT NOT NULL DEFAULT 'identity',
            mapping_version INTEGER NOT NULL DEFAULT 1,
            effective_from_utc TEXT NOT NULL DEFAULT '',
            effective_to_utc TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(source_id, source_field_key, mapping_version)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS field_ownership (
            ownership_id TEXT PRIMARY KEY,
            field_id TEXT NOT NULL REFERENCES dim_field(field_id),
            owner_source_id TEXT NOT NULL REFERENCES dim_source(source_id),
            write_policy TEXT NOT NULL DEFAULT 'APPEND_ONLY' CHECK(write_policy IN ('APPEND_ONLY', 'STATUS_OWNER', 'READ_ONLY')),
            effective_from_utc TEXT NOT NULL DEFAULT '',
            effective_to_utc TEXT,
            locked INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(field_id, effective_from_utc)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS employee_identity_rule (
            rule_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES dim_source(source_id),
            field_id TEXT NOT NULL REFERENCES dim_field(field_id),
            identifier_type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1,
            match_mode TEXT NOT NULL DEFAULT 'NORMALIZED_EXACT' CHECK(match_mode IN ('EXACT', 'NORMALIZED_EXACT')),
            allow_employee_creation INTEGER NOT NULL DEFAULT 1,
            unique_scope TEXT NOT NULL DEFAULT 'SOURCE',
            effective_from_utc TEXT NOT NULL DEFAULT '',
            effective_to_utc TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(source_id, identifier_type, priority)
        )"""
    )

    common_indexes = (
        "CREATE INDEX IF NOT EXISTS idx_employee_identifier_employee ON bridge_employee_identifier(employee_key)",
        "CREATE INDEX IF NOT EXISTS idx_employee_identifier_source ON bridge_employee_identifier(source_id, identifier_type)",
        "CREATE INDEX IF NOT EXISTS idx_source_field_mapping_active ON source_field_mapping(source_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_field_ownership_active ON field_ownership(field_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_identity_rule_priority ON employee_identity_rule(source_id, priority, active)",
    )
    for statement in common_indexes:
        bind.exec_driver_sql(statement)

    fact_tables = {
        "fact_accessnow_employee": """
            accessnow_fact_id TEXT PRIMARY KEY,
            employee_key TEXT REFERENCES dim_employee(employee_key), batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_key TEXT NOT NULL,
            source_file TEXT NOT NULL DEFAULT '', source_checksum TEXT NOT NULL DEFAULT '', row_number INTEGER NOT NULL DEFAULT 0,
            observed_date_key INTEGER REFERENCES dim_date(date_key), observed_at_utc TEXT NOT NULL DEFAULT '',
            accessnow_employee_id TEXT NOT NULL DEFAULT '', accessnow_nuid TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', vendor_name TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',
            manager_nuid TEXT NOT NULL DEFAULT '', supervisor_name TEXT NOT NULL DEFAULT '', sponsor_nuid TEXT NOT NULL DEFAULT '', sponsor_name TEXT NOT NULL DEFAULT '',
            accessnow_status TEXT NOT NULL DEFAULT '', termination_date TEXT NOT NULL DEFAULT '', onboarding_date TEXT NOT NULL DEFAULT '', production_start_date TEXT NOT NULL DEFAULT '',
            UNIQUE(batch_id, source_id, source_record_key)
        """,
        "fact_master_roster_employee": """
            master_roster_fact_id TEXT PRIMARY KEY,
            employee_key TEXT REFERENCES dim_employee(employee_key), batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_key TEXT NOT NULL,
            source_file TEXT NOT NULL DEFAULT '', source_checksum TEXT NOT NULL DEFAULT '', row_number INTEGER NOT NULL DEFAULT 0,
            observed_date_key INTEGER REFERENCES dim_date(date_key), observed_at_utc TEXT NOT NULL DEFAULT '',
            employee_number TEXT NOT NULL DEFAULT '', nuid_login_id TEXT NOT NULL DEFAULT '', npn_login_id TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', parent_client TEXT NOT NULL DEFAULT '',
            client TEXT NOT NULL DEFAULT '', program TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '', site_hr_location TEXT NOT NULL DEFAULT '',
            supervisor_employee_number TEXT NOT NULL DEFAULT '', supervisor_name TEXT NOT NULL DEFAULT '', job_code TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',
            hire_date TEXT NOT NULL DEFAULT '', project_start_date TEXT NOT NULL DEFAULT '', production_start_date TEXT NOT NULL DEFAULT '',
            actual_termination_date TEXT NOT NULL DEFAULT '', term_reason TEXT NOT NULL DEFAULT '', assignment_status TEXT NOT NULL DEFAULT '', user_principal_name TEXT NOT NULL DEFAULT '',
            UNIQUE(batch_id, source_id, source_record_key)
        """,
        "fact_roster_lock_assignment": """
            roster_lock_fact_id TEXT PRIMARY KEY,
            employee_key TEXT REFERENCES dim_employee(employee_key), batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_key TEXT NOT NULL,
            source_file TEXT NOT NULL DEFAULT '', source_checksum TEXT NOT NULL DEFAULT '', row_number INTEGER NOT NULL DEFAULT 0,
            observed_date_key INTEGER REFERENCES dim_date(date_key), observed_at_utc TEXT NOT NULL DEFAULT '',
            vendor_name TEXT NOT NULL DEFAULT '', vendor_employee_id TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '', supervisor_name TEXT NOT NULL DEFAULT '',
            onboarding_date TEXT NOT NULL DEFAULT '', production_start_date TEXT NOT NULL DEFAULT '', assignment_status TEXT NOT NULL DEFAULT '', work_order_id TEXT NOT NULL DEFAULT '',
            UNIQUE(batch_id, source_id, source_record_key)
        """,
        "fact_rsr_assignment": """
            rsr_fact_id TEXT PRIMARY KEY,
            employee_key TEXT REFERENCES dim_employee(employee_key), batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_key TEXT NOT NULL,
            source_file TEXT NOT NULL DEFAULT '', source_checksum TEXT NOT NULL DEFAULT '', row_number INTEGER NOT NULL DEFAULT 0,
            observed_date_key INTEGER REFERENCES dim_date(date_key), observed_at_utc TEXT NOT NULL DEFAULT '',
            supplier_reference TEXT NOT NULL DEFAULT '', worker_id TEXT NOT NULL DEFAULT '', buyer_reference TEXT NOT NULL DEFAULT '', work_order_id TEXT NOT NULL DEFAULT '',
            worker TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', vendor_name TEXT NOT NULL DEFAULT '',
            worker_status TEXT NOT NULL DEFAULT '', worker_start_date TEXT NOT NULL DEFAULT '', worker_end_date TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',
            supervisor_name TEXT NOT NULL DEFAULT '', statement_of_work TEXT NOT NULL DEFAULT '', supplier_name TEXT NOT NULL DEFAULT '',
            UNIQUE(batch_id, source_id, source_record_key)
        """,
    }
    for table, definition in fact_tables.items():
        bind.exec_driver_sql(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")
        bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS idx_{table}_employee ON {table}(employee_key)")
        bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS idx_{table}_observed ON {table}(observed_date_key, observed_at_utc)")

    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS fact_employee_status_event (
            status_event_id TEXT PRIMARY KEY,
            employee_key TEXT NOT NULL REFERENCES dim_employee(employee_key),
            accessnow_fact_id TEXT NOT NULL REFERENCES fact_accessnow_employee(accessnow_fact_id),
            source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_id TEXT NOT NULL,
            status_code TEXT NOT NULL, effective_date_key INTEGER REFERENCES dim_date(date_key), effective_date TEXT NOT NULL DEFAULT '',
            owner_source_system TEXT NOT NULL DEFAULT 'ACCESSNOW' CHECK(owner_source_system = 'ACCESSNOW'),
            observed_at_utc TEXT NOT NULL DEFAULT '', created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(employee_key, source_record_id, status_code)
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_employee_status_latest ON fact_employee_status_event(employee_key, effective_date, observed_at_utc)")
    bind.exec_driver_sql(
        """CREATE TRIGGER IF NOT EXISTS trg_status_event_accessnow_source
        BEFORE INSERT ON fact_employee_status_event
        WHEN NOT EXISTS (
            SELECT 1 FROM dim_source
            WHERE dim_source.source_id = NEW.source_id
              AND UPPER(dim_source.source_system) = 'ACCESSNOW'
        )
        BEGIN SELECT RAISE(ABORT, 'employee status events are owned by ACCESSNOW'); END"""
    )
    bind.exec_driver_sql(
        """CREATE TRIGGER IF NOT EXISTS trg_status_event_immutable_update
        BEFORE UPDATE ON fact_employee_status_event
        BEGIN SELECT RAISE(ABORT, 'employee status events are append-only'); END"""
    )
    bind.exec_driver_sql(
        """CREATE TRIGGER IF NOT EXISTS trg_status_event_immutable_delete
        BEFORE DELETE ON fact_employee_status_event
        BEGIN SELECT RAISE(ABORT, 'employee status events are append-only'); END"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS fact_source_field_value (
            source_value_id TEXT PRIMARY KEY,
            employee_key TEXT REFERENCES dim_employee(employee_key), source_id TEXT NOT NULL REFERENCES dim_source(source_id),
            source_system TEXT NOT NULL, source_record_id TEXT NOT NULL, source_record_key TEXT NOT NULL DEFAULT '',
            batch_id TEXT NOT NULL REFERENCES import_batches(batch_id), field_id TEXT NOT NULL REFERENCES dim_field(field_id),
            value_text TEXT NOT NULL DEFAULT '', observed_date_key INTEGER REFERENCES dim_date(date_key), observed_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(source_system, source_record_id, field_id)
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_source_field_value_employee ON fact_source_field_value(employee_key, field_id, observed_at_utc)")
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS fact_employee_field_history (
            history_id TEXT PRIMARY KEY,
            employee_key TEXT NOT NULL REFERENCES dim_employee(employee_key), field_id TEXT NOT NULL REFERENCES dim_field(field_id),
            owner_source_id TEXT NOT NULL REFERENCES dim_source(source_id), source_record_id TEXT NOT NULL DEFAULT '', value_text TEXT NOT NULL DEFAULT '',
            version_number INTEGER NOT NULL DEFAULT 1, observed_date_key INTEGER REFERENCES dim_date(date_key),
            observed_at_utc TEXT NOT NULL DEFAULT '', created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(employee_key, field_id, version_number)
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_employee_field_history_latest ON fact_employee_field_history(employee_key, field_id, version_number)")
    for table in (
        "fact_accessnow_employee",
        "fact_master_roster_employee",
        "fact_roster_lock_assignment",
        "fact_rsr_assignment",
        "fact_source_field_value",
    ):
        bind.exec_driver_sql(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'source facts are append-only'); END"""
        )
        bind.exec_driver_sql(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'source facts are append-only'); END"""
        )


def downgrade() -> None:
    pass
