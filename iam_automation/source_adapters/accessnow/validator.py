"""Validate normalized AccessNow rows."""

from __future__ import annotations


def validation_error(payload: dict[str, str], source_key: str, seen: set[str]) -> str:
    if not payload.get("accessnow_employee_id"):
        return "Missing Employee ID."
    if source_key in seen:
        return "Duplicate Employee ID after active/termination merge."
    if not payload.get("first_name") and not payload.get("last_name"):
        return "Missing employee name."
    if not payload.get("accessnow_status"):
        return "Missing Employee status."
    return ""
