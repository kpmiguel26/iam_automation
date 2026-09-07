"""Normalize AccessNow report labels and statuses."""

from __future__ import annotations

from ...application.status_catalog import normalize_accessnow_status


def key(value: object) -> str:
    return "_".join("".join(char.lower() if char.isalnum() else " " for char in str(value)).split())


def value(value: object) -> str:
    return str(value or "").strip()


def normalize_row(raw: dict[str, object]) -> dict[str, str]:
    values = {key(name): value(item) for name, item in raw.items() if name}
    aliases = {
        "employee_id": "accessnow_employee_id",
        "nuid": "accessnow_nuid",
        "first_name": "first_name",
        "last_name": "last_name",
        "kp_email": "email",
        "employee_status": "accessnow_status",
        "company_name": "vendor_name",
        "workforce_class": "job_title",
        "kp_start_date": "onboarding_date",
        "kp_sunset_date": "production_start_date",
        "terminated_date": "terminated_date",
        "manager_nuid": "manager_nuid",
        "manager_name": "supervisor_name",
        "sponsor_nuid": "sponsor_nuid",
        "sponsor_name": "sponsor_name",
        "kp_create_date": "created_date",
    }
    normalized = {aliases.get(name, name): item.strip() for name, item in values.items() if item.strip()}
    normalized["accessnow_status"] = normalize_accessnow_status(normalized.get("accessnow_status", ""))
    return normalized


def normalize_status(value: object) -> str:
    return normalize_accessnow_status(value)
