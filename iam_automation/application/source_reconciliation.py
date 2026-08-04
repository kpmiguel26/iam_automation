"""Shared identity resolution and source identifier registration."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import WorkerIdentifierModel, WorkerModel


def source_identifiers(source_system: str, payload: dict[str, object]) -> list[tuple[str, str]]:
    fields = {
        "ACCESSNOW": (("ACCESSNOW_EMPLOYEE_ID", "accessnow_employee_id"), ("ACCESSNOW_NUID", "accessnow_nuid"), ("ACCESSNOW_MANAGER_NUID", "manager_nuid"), ("ACCESSNOW_SPONSOR_NUID", "sponsor_nuid")),
        "RSR_SUPPLIER_WORKER_DETAILS": (("RSR_WORKER_ID", "worker_id"), ("VENDOR_EMPLOYEE_ID", "supplier_reference"), ("BUYER_REFERENCE", "buyer_reference"), ("WORK_ORDER_ID", "work_order_id")),
        "ROSTER_LOCK": (("VENDOR_EMPLOYEE_ID", "vendor_employee_id"),),
    }
    return [(kind, value) for kind, field in fields.get(source_system, ()) if (value := str(payload.get(field) or "").strip())]


def _match_types(source_system: str, identifier_type: str) -> set[str]:
    return {
        ("ACCESSNOW", "ACCESSNOW_NUID"): {"ACCESSNOW_NUID", "BUYER_REFERENCE"},
        ("RSR_SUPPLIER_WORKER_DETAILS", "BUYER_REFERENCE"): {"ACCESSNOW_NUID", "BUYER_REFERENCE"},
    }.get((source_system, identifier_type), {identifier_type})


def find_worker_matches(session, source_system: str, payload: dict[str, object]) -> tuple[list[str], str]:
    """Find one canonical worker using strong IDs, then email/name fallback."""
    for identifier_type, value in source_identifiers(source_system, payload):
        if identifier_type in {"ACCESSNOW_MANAGER_NUID", "ACCESSNOW_SPONSOR_NUID", "WORK_ORDER_ID"}:
            continue
        matches = session.scalars(select(WorkerIdentifierModel.worker_id).where(
            WorkerIdentifierModel.identifier_type.in_(_match_types(source_system, identifier_type)),
            WorkerIdentifierModel.normalized_value == value.casefold(),
            WorkerIdentifierModel.active.is_(True),
        )).all()
        if matches:
            active = session.scalars(select(WorkerModel.worker_id).where(
                WorkerModel.worker_id.in_(set(matches)), WorkerModel.superseded_by_worker_id.is_(None)
            )).all()
            if active:
                return sorted(set(active)), "Exact source identifier match"
    email = str(payload.get("email") or payload.get("vendor_email") or payload.get("vendor_email_address") or "").strip().casefold()
    if email:
        matches = session.scalars(select(WorkerModel.worker_id).where(func.lower(WorkerModel.canonical_email) == email, WorkerModel.superseded_by_worker_id.is_(None))).all()
        if matches:
            return sorted(set(matches)), "Canonical email match"
    first = str(payload.get("first_name") or payload.get("employee_first_name") or "").strip().casefold()
    last = str(payload.get("last_name") or payload.get("employee_last_name") or "").strip().casefold()
    if first and last:
        matches = session.scalars(select(WorkerModel.worker_id).where(func.lower(WorkerModel.first_name) == first, func.lower(WorkerModel.last_name) == last, WorkerModel.superseded_by_worker_id.is_(None))).all()
        if matches:
            return sorted(set(matches)), "Canonical name match"
    return [], "No canonical match"


def ensure_source_identifiers(session, worker_id: str, source_system: str, payload: dict[str, object], now: str) -> None:
    """Register every source identifier idempotently without overwriting values."""
    for identifier_type, value in source_identifiers(source_system, payload):
        normalized = value.casefold()
        existing = session.scalar(select(WorkerIdentifierModel).where(
            WorkerIdentifierModel.source_system == source_system,
            WorkerIdentifierModel.identifier_type == identifier_type,
            WorkerIdentifierModel.normalized_value == normalized,
        ))
        if existing is None:
            session.add(WorkerIdentifierModel(
                identifier_id=str(uuid.uuid4()), worker_id=worker_id, source_system=source_system,
                identifier_type=identifier_type, identifier_value=value, normalized_value=normalized,
                confidence="HIGH", created_at_utc=now,
            ))
