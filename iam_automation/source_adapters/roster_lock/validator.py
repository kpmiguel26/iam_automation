"""Validate normalized Roster Lock rows."""

from __future__ import annotations


def validation_error(normalized: dict[str, object], source_key: str, seen_keys: set[str]) -> str | None:
    if not str(normalized.get("vendor_employee_id") or "").strip():
        return "Required field Vendor employee ID is missing."
    if not str(normalized.get("vendor_name") or "").strip():
        return "Required field Vendor Name is missing."
    if source_key in seen_keys:
        return f"Duplicate Roster Lock source key detected: {source_key}."
    return None
