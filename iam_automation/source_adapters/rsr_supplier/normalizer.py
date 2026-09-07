"""Normalize Fieldglass RSR worker detail rows."""

from __future__ import annotations

from datetime import datetime


HEADER_ALIASES = {
    "contractor_id": "worker_id",
    "contractor": "worker",
    "contractor_status": "worker_status",
    "contractor_start_date": "worker_start_date",
    "contractor_end_date": "worker_end_date",
    "statement_of_work_id": "work_order_id",
    "external_reference_id": "statement_of_work",
    "contractor_owner": "worker_primary_contact",
    "supplier": "supplier_name",
}


def header_key(value: object) -> str:
    return "_".join(str(value or "").strip().casefold().replace("/", " ").replace("-", " ").split())


def value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def normalize_payload(payload: dict[str, str]) -> dict[str, str]:
    worker = payload.get("worker", "")
    if "," in worker:
        last, first = (part.strip() for part in worker.split(",", 1))
        payload.setdefault("first_name", first)
        payload.setdefault("last_name", last)
    else:
        parts = worker.split()
        payload.setdefault("first_name", parts[0] if parts else "")
        payload.setdefault("last_name", " ".join(parts[1:]))
    payload["supplier_reference"] = payload.get("supplier_reference", "").strip()
    payload["worker_id"] = payload.get("worker_id", "").strip()
    return payload


def is_report_footer(payload: dict[str, str], required_headers: set[str]) -> bool:
    """Ignore Fieldglass report metadata rows after the worker data."""
    if any(str(payload.get(field) or "").strip() for field in required_headers):
        return False
    report_text = " ".join(str(value or "").strip().casefold() for value in payload.values())
    return "the data contained in this report is as of" in report_text or ("date:" in report_text and "us/central" in report_text)
