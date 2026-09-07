"""Validate normalized Master Roster rows."""

from __future__ import annotations


def validation_error(normalized: dict[str, object], source_key: str, seen_keys: set[str]) -> str | None:
    if not source_key:
        return "Required field Employee Number is missing."
    if not str(normalized.get("employee_name") or "").strip():
        return "Required field Employee Name is missing."
    if source_key in seen_keys:
        return f"Duplicate Master Roster Employee Number detected: {source_key}."
    return None
