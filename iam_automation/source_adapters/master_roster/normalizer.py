"""Normalize Master Roster row labels and values."""

from __future__ import annotations

from datetime import date, datetime


def normalize_row(payload: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in payload.items():
        canonical = "_".join("".join(character.lower() if character.isalnum() else " " for character in key).split())
        normalized[canonical] = value
    aliases = {
        "source_column_1": "source_row_number",
        "user_principal_name": "email",
        "logonid": "nuid_login_id",
        "logonid_2": "npn_login_id",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    employee_name = str(normalized.get("employee_name") or "").strip()
    if employee_name and not normalized.get("first_name"):
        parts = employee_name.split()
        normalized["first_name"] = parts[0]
        normalized["last_name"] = " ".join(parts[1:])
    return normalized


def json_value(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
