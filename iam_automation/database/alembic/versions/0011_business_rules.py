"""Add post-import business rule definitions and findings."""

from alembic import op


revision = "0011_business_rules"
down_revision = "0010_accessnow_match_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS business_rules (
            rule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            rule_type TEXT NOT NULL DEFAULT 'RECORD_CONDITION',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            current_version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT ''
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS business_rule_versions (
            rule_version_id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL REFERENCES business_rules(rule_id),
            version INTEGER NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            condition_json TEXT NOT NULL DEFAULT '{}',
            severity TEXT NOT NULL DEFAULT 'WARNING',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(rule_id, version)
        )"""
    )
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS rule_findings (
            finding_id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            rule_version_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            record_id TEXT,
            worker_id TEXT,
            source_system TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'WARNING',
            status TEXT NOT NULL DEFAULT 'OPEN',
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            fingerprint TEXT NOT NULL UNIQUE,
            created_at_utc TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL DEFAULT '',
            acknowledged_by TEXT,
            acknowledged_at_utc TEXT
        )"""
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_business_rules_status ON business_rules (status)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_rule_findings_status ON rule_findings (status, severity, created_at_utc)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_rule_findings_batch ON rule_findings (batch_id, record_id)")


def downgrade() -> None:
    # Findings are audit evidence; this migration is intentionally additive.
    pass
