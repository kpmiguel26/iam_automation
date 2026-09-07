"""Compare source observations and persist only material employee changes."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ..infrastructure.sqlite.orm import IngestionRecordModel, WorkerEngagementModel, WorkerIdentifierModel, WorkerSourceLineageModel
from .source_reconciliation import source_identifiers
from .star_schema_writer import StarSchemaWriter


SOURCE_ENGAGEMENT_FIELDS = {
    "vendor_name": "vendor_name", "program": "program", "project": "project",
    "lob": "lob", "supervisor_name": "supervisor_name", "job_title": "job_title",
    "country": "country", "site_location": "site_location", "onboarding_date": "onboarding_date",
    "worker_start_date": "onboarding_date", "worker_end_date": "production_start_date",
    "production_start_date": "production_start_date", "status": "status", "worker_status": "status", "fg_status": "status", "accessnow_status": "status", "npn": "npn",
    "resident_license_state": "license_state", "resident_license_number": "license_number",
    "taxonomy": "taxonomy_code", "taxonomy_code": "taxonomy_code", "key_billable_function": "key_billable_function",
    "statement_of_work": "statement_of_work", "work_order_id": "work_order_id",
    "worker_primary_contact": "primary_contact_name", "sponsor_name": "primary_contact_name", "sow_worker_role": "job_title",
}


def comparison_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def latest_engagement(session, worker_id: str, source_system: str) -> WorkerEngagementModel | None:
    return session.scalar(select(WorkerEngagementModel).where(
        WorkerEngagementModel.worker_id == worker_id,
        WorkerEngagementModel.source_system == source_system,
    ).order_by(WorkerEngagementModel.updated_at_utc.desc(), WorkerEngagementModel.created_at_utc.desc()))


def material_source_fields(session, worker_id: str, source_system: str, payload: dict[str, object]) -> set[str]:
    engagement = latest_engagement(session, worker_id, source_system)
    changes = set()
    for source_field, attribute in SOURCE_ENGAGEMENT_FIELDS.items():
        incoming = comparison_text(payload.get(source_field))
        if incoming and (engagement is None or incoming != comparison_text(getattr(engagement, attribute, ""))):
            changes.add(source_field)
    known = {
        (str(item.identifier_type), comparison_text(item.normalized_value))
        for item in session.scalars(select(WorkerIdentifierModel).where(
            WorkerIdentifierModel.worker_id == worker_id,
            WorkerIdentifierModel.source_system == source_system,
            WorkerIdentifierModel.active.is_(True),
        )).all()
    }
    if any((kind, comparison_text(value)) not in known for kind, value in source_identifiers(source_system, payload)):
        changes.add("identifiers")
    return changes


def apply_engagement_changes(session, engagement: WorkerEngagementModel, payload: dict[str, object], changed_fields: set[str], now: str) -> None:
    changed = False
    for source_field in changed_fields - {"identifiers"}:
        attribute = SOURCE_ENGAGEMENT_FIELDS.get(source_field)
        if not attribute:
            continue
        incoming = str(payload.get(source_field) or "").strip()
        if source_field == "taxonomy" and not incoming:
            incoming = str(payload.get("taxonomy_code") or "").strip()
        if source_field == "taxonomy_code" and not incoming:
            incoming = str(payload.get("taxonomy") or "").strip()
        if incoming and comparison_text(getattr(engagement, attribute, "")) != comparison_text(incoming):
            setattr(engagement, attribute, incoming)
            changed = True
    if changed:
        engagement.updated_at_utc = now


def record_changed_lineage(session, record: IngestionRecordModel, worker_id: str, now: str, changed_fields: set[str], engagement_id: str | None = None) -> None:
    payload = StarSchemaWriter.payload_for_record(session, record)
    existing = {
        (item.source_file, item.row_number, item.field_name)
        for item in session.scalars(select(WorkerSourceLineageModel).where(
            WorkerSourceLineageModel.worker_id == worker_id,
            WorkerSourceLineageModel.source_system == record.source_system,
            WorkerSourceLineageModel.source_file == record.source_file,
            WorkerSourceLineageModel.row_number == record.row_number,
        )).all()
    }
    for field_name in changed_fields - {"identifiers"}:
        if field_name not in payload or not str(payload[field_name] or "").strip():
            continue
        if (record.source_file, record.row_number, field_name) in existing:
            continue
        value = str(payload[field_name] or "").strip()
        session.add(WorkerSourceLineageModel(
            lineage_id=str(uuid.uuid4()), worker_id=worker_id, engagement_id=engagement_id,
            batch_id=record.batch_id, source_system=record.source_system,
            source_file=record.source_file, source_checksum=record.source_checksum,
            row_number=record.row_number, field_name=field_name,
            raw_value=value, normalized_value=value, observed_at_utc=now,
        ))
