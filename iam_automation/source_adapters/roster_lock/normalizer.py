"""Normalize Roster Lock row labels and values."""

from __future__ import annotations

from datetime import datetime


def normalize_row(payload: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in payload.items():
        canonical = "_".join("".join(character.lower() if character.isalnum() else " " for character in key).split())
        normalized[canonical] = value
    aliases = {
        "employee_first_name": "first_name",
        "employee_last_name": "last_name",
        "vendor_email_address": "email",
        # Keep the source header available while exposing the governed name
        # used by the rule catalog and typed assignment fact.
        "status": "assignment_status",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    return normalized


def json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
