"""Merge AccessNow active and termination report rows."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ...application.status_catalog import status_rank


def merge_rows(rows: Iterable[tuple[Path, int, dict[str, str]]]) -> tuple[dict[str, tuple[Path, int, dict[str, str]]], int]:
    """Merge rows by employee ID, retaining the strongest lifecycle status."""
    merged: dict[str, tuple[Path, int, dict[str, str]]] = {}
    total_rows = 0
    for path, row_number, payload in rows:
        total_rows += 1
        key = payload.get("accessnow_employee_id", "") or f"ROW:{path.name}:{row_number}"
        current = merged.get(key)
        if current is None:
            merged[key] = (path, row_number, payload)
            continue
        current_payload = current[2]
        current_rank = status_rank(current_payload.get("accessnow_status", ""))
        incoming_rank = status_rank(payload.get("accessnow_status", ""))
        for field_name, incoming_value in payload.items():
            if not current_payload.get(field_name) or (incoming_rank > current_rank and field_name in {"accessnow_status", "terminated_date"}):
                current_payload[field_name] = incoming_value
    return merged, total_rows
