"""Seed the governed source and field catalog used by rule configuration."""

from __future__ import annotations

import uuid

from alembic import op


revision = "0022_source_rule_catalog"
down_revision = "0021_pin_rule_calendar_version"
branch_labels = None
depends_on = None


SOURCE_FIELDS = {
    "ROSTER_LOCK": (
        "vendor_employee_id", "vendor_name", "first_name", "last_name", "email",
        "job_title", "supervisor_name", "onboarding_date", "production_start_date",
        "assignment_status", "work_order_id",
    ),
    "MASTER_ROSTER": (
        "employee_number", "employee_name", "first_name", "last_name", "email",
        "nuid_login_id", "npn_login_id", "parent_client", "client", "program", "project",
        "site_hr_location", "supervisor_employee_number", "supervisor_name", "job_code",
        "job_title", "hire_date", "project_start_date", "production_start_date",
        "actual_termination_date", "term_reason", "assignment_status", "status", "user_principal_name",
    ),
    "RSR_SUPPLIER_WORKER_DETAILS": (
        "supplier_reference", "worker_id", "buyer_reference", "work_order_id", "worker",
        "first_name", "last_name", "email", "vendor_name", "worker_status", "worker_start_date",
        "worker_end_date", "job_title", "supervisor_name", "statement_of_work", "supplier_name",
    ),
    "ACCESSNOW": (
        "accessnow_employee_id", "accessnow_nuid", "first_name", "last_name", "email",
        "vendor_name", "job_title", "manager_nuid", "supervisor_name", "sponsor_nuid",
        "sponsor_name", "accessnow_status", "termination_date", "onboarding_date",
        "production_start_date",
    ),
}

SOURCE_LABELS = {
    "ROSTER_LOCK": "Roster Lock",
    "MASTER_ROSTER": "Master Roster",
    "RSR_SUPPLIER_WORKER_DETAILS": "Fieldglass / RSR Supplier Worker Details",
    "ACCESSNOW": "AccessNow",
}


def _id(prefix: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"iam-automation:{prefix}:{value}"))


def upgrade() -> None:
    bind = op.get_bind()
    for source_system, label in SOURCE_LABELS.items():
        source_id = _id("source", source_system)
        bind.exec_driver_sql(
            "INSERT OR IGNORE INTO dim_source (source_id, source_system, label, active) VALUES (?, ?, ?, 1)",
            (source_id, source_system, label),
        )
        for field_key in SOURCE_FIELDS[source_system]:
            field_id = _id("field", field_key)
            bind.exec_driver_sql(
                "INSERT OR IGNORE INTO dim_field (field_id, field_key, label, rule_enabled, active) VALUES (?, ?, ?, 1, 1)",
                (field_id, field_key, field_key.replace("_", " ").title()),
            )
            bind.exec_driver_sql(
                """INSERT OR IGNORE INTO source_field_mapping
                    (mapping_id, source_id, source_field_key, field_id, target_kind,
                     transform_name, mapping_version, effective_from_utc, active,
                     created_by, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, 'FACT', 'identity', 1, datetime('now'), 1,
                            'system', datetime('now'), datetime('now'))""",
                (_id("source-field-mapping", f"{source_system}:{field_key}"), source_id, field_key, field_id),
            )


def downgrade() -> None:
    # Source and field configuration is user-visible data; retain it.
    pass
