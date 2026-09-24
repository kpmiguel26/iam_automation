"""
File: iam_automation/application/source_reconciliation.py
Purpose: Shared identity resolution and source identifier registration.
Responsibilities: Exposes or coordinates: source_identifiers, _match_types, find_worker_matches, ensure_source_identifiers.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import IngestionRecordModel, WorkerIdentifierModel, WorkerModel
from .source_date import parse_source_date
from .status_catalog import is_inactive_source_status, normalize_accessnow_status
from ..infrastructure.sqlite.star_schema_writer import StarSchemaWriter


def source_identifiers(source_system: str, payload: dict[str, object]) -> list[tuple[str, str]]:
    fields = {
        "ACCESSNOW": (("ACCESSNOW_EMPLOYEE_ID", "accessnow_employee_id"), ("ACCESSNOW_NUID", "accessnow_nuid"), ("ACCESSNOW_MANAGER_NUID", "manager_nuid"), ("ACCESSNOW_SPONSOR_NUID", "sponsor_nuid")),
        "RSR_SUPPLIER_WORKER_DETAILS": (("RSR_WORKER_ID", "worker_id"), ("VENDOR_EMPLOYEE_ID", "supplier_reference"), ("BUYER_REFERENCE", "buyer_reference"), ("WORK_ORDER_ID", "work_order_id")),
        "ROSTER_LOCK": (("VENDOR_EMPLOYEE_ID", "vendor_employee_id"),),
        "MASTER_ROSTER": (("MASTER_EMPLOYEE_NUMBER", "employee_number"), ("MASTER_NUID", "nuid_login_id"), ("MASTER_NPN", "npn_login_id")),
    }
    return [(kind, value) for kind, field in fields.get(source_system, ()) if (value := str(payload.get(field) or "").strip())]


def _match_types(source_system: str, identifier_type: str) -> set[str]:
    """Return the identifier aliases that represent the same business key.

    These are intentionally narrow equivalence classes.  A NUID is not the
    same value as an NPN, and worker/work-order identifiers are not identity
    keys.  The source system is kept in the signature for callers and future
    source-specific rules, but the aliases are shared across source systems.
    """
    for aliases in (
        {"ACCESSNOW_NUID", "MASTER_NUID", "BUYER_REFERENCE"},
        {"ACCESSNOW_EMPLOYEE_ID", "MASTER_EMPLOYEE_NUMBER", "VENDOR_EMPLOYEE_ID"},
    ):
        if identifier_type in aliases:
            return aliases
    return {identifier_type}


def find_worker_matches(session, source_system: str, payload: dict[str, object]) -> tuple[list[str], str]:
    """Find canonical workers using all strong evidence, then safe fallbacks.

    DEPRECATED (migration pending): this Employee-specific resolver is the
    active runtime path until a runtime Object Engine consumes approved
    Template Object relationships and passes matching parity. Keep its current
    callers and result/reason contract during the parallel phase.

    The previous implementation returned on the first identifier.  That made
    the result dependent on field order and allowed two identifiers in one
    source row to point at different canonical workers without surfacing the
    conflict.  We now collect every strong match first; more than one worker
    is ambiguous and must not create a new canonical employee silently.
    """
    strong_matches: dict[str, set[str]] = {}
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
            for worker_id in active:
                strong_matches.setdefault(worker_id, set()).add(identifier_type)
    if strong_matches:
        if len(strong_matches) == 1:
            return sorted(strong_matches), "Exact source identifier match"
        return sorted(strong_matches), "Conflicting source identifiers"

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


def _lifecycle_date(source_system: str, payload: dict[str, object], status: str) -> date | None:
    """Return a business/effective date, never a persistence timestamp."""
    if source_system == "ACCESSNOW" and is_inactive_source_status(status):
        keys = ("terminated_date", "deactivated_date", "termination_date", "end_date", "production_start_date")
    elif source_system in {"ACCESSNOW", "ROSTER_LOCK"}:
        # ``created_date`` is a source-record creation field, not proof of a
        # lifecycle event. Do not silently turn it into an effective date.
        keys = ("onboarding_date", "worker_start_date", "start_date", "hire_date")
    else:
        keys = ("effective_date", "onboarding_date", "worker_start_date", "start_date", "hire_date")
    return next((parsed for key in keys if (parsed := parse_source_date(payload.get(key))) is not None), None)


def reconcile_worker_status_in_session(session, worker_id: str) -> str:
    """Derive an analytical status from dated source evidence.

    Source rows remain immutable observations. This function only updates the
    analytical Worker projection and deliberately refuses to choose a status
    when an inactive observation has no effective date or when dated events
    conflict on the same business day.
    """
    worker = session.get(WorkerModel, worker_id)
    if worker is None:
        raise ValueError("Worker was not found.")
    records = session.scalars(select(IngestionRecordModel).where(
        IngestionRecordModel.matched_worker_id == worker_id,
        IngestionRecordModel.status.in_(("STAGED", "MATCHED", "LINKED", "CURRENT", "APPLIED")),
    )).all()
    events: list[tuple[date, str]] = []
    undated_inactive = False
    for record in records:
        try:
            payload = StarSchemaWriter.payload_for_record(session, record)
        except json.JSONDecodeError:
            payload = {}
        if record.source_system == "ACCESSNOW":
            status = normalize_accessnow_status(payload.get("accessnow_status"))
            if status not in {"ACTIVE", "DEACTIVATED", "TERMINATED"}:
                continue
            effective_date = _lifecycle_date(record.source_system, payload, status)
            if effective_date is None:
                undated_inactive = undated_inactive or is_inactive_source_status(status)
                continue
            events.append((effective_date, status))
        elif record.source_system == "ROSTER_LOCK":
            # Roster Lock is treated as active presence only when it carries a
            # usable business date. It is not a global source-priority rule.
            effective_date = _lifecycle_date(record.source_system, payload, "ACTIVE")
            if effective_date is not None:
                events.append((effective_date, "ACTIVE"))

    if undated_inactive:
        resolved_status = "INSUFFICIENT_EVIDENCE"
    elif not events:
        resolved_status = str(worker.status or "PENDING")
    else:
        latest_date = max(item[0] for item in events)
        latest_statuses = {status for event_date, status in events if event_date == latest_date}
        resolved_status = next(iter(latest_statuses)) if len(latest_statuses) == 1 else "INSUFFICIENT_EVIDENCE"
    worker.status = resolved_status
    return resolved_status
#endfile
