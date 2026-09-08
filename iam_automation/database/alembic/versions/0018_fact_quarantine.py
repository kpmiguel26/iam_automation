"""Create the master quarantine fact for rule violations."""

from alembic import op


revision = "0018_fact_quarantine"
down_revision = "0017_rule_execution_phase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS fact_quarantine (
            quarantine_fact_id TEXT PRIMARY KEY,
            finding_id TEXT NOT NULL UNIQUE,
            employee_key TEXT REFERENCES dim_employee(employee_key),
            worker_id TEXT REFERENCES workers(worker_id),
            batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
            record_id TEXT,
            source_id TEXT REFERENCES dim_source(source_id),
            field_id TEXT REFERENCES dim_field(field_id),
            source_system TEXT NOT NULL DEFAULT '',
            source_record_key TEXT NOT NULL DEFAULT '',
            rule_id TEXT NOT NULL,
            rule_version_id TEXT NOT NULL,
            field_key TEXT NOT NULL DEFAULT '',
            operator TEXT NOT NULL DEFAULT '',
            expected_value TEXT NOT NULL DEFAULT '',
            observed_value TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'WARNING',
            status TEXT NOT NULL DEFAULT 'OPEN',
            rule_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            resolved_by TEXT,
            resolved_at_utc TEXT
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fact_quarantine_status ON fact_quarantine(status, severity, created_at_utc)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fact_quarantine_employee ON fact_quarantine(employee_key, worker_id, status)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fact_quarantine_source ON fact_quarantine(source_system, batch_id, record_id)")

    # Preserve findings already present in databases upgraded from the
    # previous model. New evaluations create a fully enriched fact in Python.
    bind.exec_driver_sql(
        """INSERT OR IGNORE INTO fact_quarantine (
            quarantine_fact_id, finding_id, employee_key, worker_id, batch_id,
            record_id, source_id, field_id, source_system, source_record_key,
            rule_id, rule_version_id, field_key, operator, expected_value,
            observed_value, severity, status, rule_name, reason, evidence_json,
            created_at_utc, updated_at_utc
        )
        SELECT
            'quarantine:' || finding.finding_id,
            finding.finding_id,
            employee.employee_key,
            finding.worker_id,
            finding.batch_id,
            finding.record_id,
            source.source_id,
            field.field_id,
            finding.source_system,
            COALESCE(record.source_record_key, ''),
            finding.rule_id,
            finding.rule_version_id,
            COALESCE(json_extract(version.condition_json, '$.field'), ''),
            COALESCE(json_extract(version.condition_json, '$.operator'), ''),
            COALESCE(CAST(json_extract(version.condition_json, '$.value') AS TEXT), ''),
            COALESCE(CAST(json_extract(finding.evidence_json, '$.payload.' || json_extract(version.condition_json, '$.field')) AS TEXT), ''),
            finding.severity,
            finding.status,
            finding.title,
            finding.message,
            finding.evidence_json,
            finding.created_at_utc,
            finding.updated_at_utc
        FROM rule_findings AS finding
        JOIN business_rule_versions AS version ON version.rule_version_id = finding.rule_version_id
        LEFT JOIN ingestion_records AS record ON record.record_id = finding.record_id
        LEFT JOIN dim_source AS source ON source.source_system = finding.source_system
        LEFT JOIN dim_field AS field ON field.field_key = json_extract(version.condition_json, '$.field')
        LEFT JOIN dim_employee AS employee ON employee.employee_key = finding.worker_id"""
    )


def downgrade() -> None:
    pass
