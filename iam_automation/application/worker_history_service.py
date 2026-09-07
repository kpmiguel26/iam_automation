"""
File: iam_automation/application/worker_history_service.py
Purpose: Implements the application service for worker history service workflows.
Responsibilities: Exposes or coordinates: _now, worker_snapshot, record_worker_version, version_dict, backfill_missing_worker_versions.
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
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import (
    WorkerEngagementModel,
    WorkerIdentifierModel,
    WorkerModel,
    WorkerProfileVersionModel,
    FactWorkerFieldHistoryModel,
    WorkerSourceLineageModel,
    orm_session,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_snapshot(session, worker_id: str) -> dict[str, object]:
    worker = session.get(WorkerModel, worker_id)
    if worker is None:
        raise ValueError("Worker was not found.")
    identifiers = session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker_id).order_by(WorkerIdentifierModel.identifier_type)).all()
    engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.engagement_id)).all()
    lineage = session.scalars(select(WorkerSourceLineageModel).where(WorkerSourceLineageModel.worker_id == worker_id).order_by(WorkerSourceLineageModel.lineage_id)).all()
    return {
        "worker_id": worker.worker_id,
        "record_version": worker.record_version,
        "first_name": worker.first_name,
        "last_name": worker.last_name,
        "display_name": worker.display_name,
        "canonical_email": worker.canonical_email,
        "status": worker.status,
        "superseded_by_worker_id": worker.superseded_by_worker_id,
        "identifiers": [
            {"source_system": item.source_system, "identifier_type": item.identifier_type, "identifier_value": item.identifier_value, "normalized_value": item.normalized_value, "active": item.active}
            for item in identifiers
        ],
        "engagements": [
            {"engagement_id": item.engagement_id, "vendor_name": item.vendor_name, "program": item.program, "project": item.project, "lob": item.lob, "supervisor_name": item.supervisor_name, "job_title": item.job_title, "country": item.country, "site_location": item.site_location, "onboarding_date": item.onboarding_date, "production_start_date": item.production_start_date, "status": item.status, "npn": item.npn, "license_state": item.license_state, "license_number": item.license_number, "taxonomy_code": item.taxonomy_code, "key_billable_function": item.key_billable_function, "statement_of_work": item.statement_of_work, "work_order_id": item.work_order_id, "primary_contact_name": item.primary_contact_name, "source_system": item.source_system}
            for item in engagements
        ],
        "lineage_count": len(lineage),
        "lineage": [
            {"lineage_id": item.lineage_id, "field_name": item.field_name, "normalized_value": item.normalized_value, "raw_value": item.raw_value, "source_system": item.source_system}
            for item in lineage
        ],
    }


def record_worker_version(
    session,
    worker_id: str,
    *,
    actor: str = "system",
    change_type: str = "SOURCE_IMPORT",
    source_system: str = "",
    source_file: str = "",
    source_checksum: str = "",
    source_record_key: str = "",
    changed_fields: list[str] | None = None,
) -> WorkerProfileVersionModel:
    """Append one immutable snapshot. Call after related ORM objects are flushed."""
    session.flush()
    current = int(session.scalar(select(func.max(WorkerProfileVersionModel.version_number)).where(WorkerProfileVersionModel.worker_id == worker_id)) or 0)
    worker = session.get(WorkerModel, worker_id)
    if worker is None:
        raise ValueError("Worker was not found.")
    next_version = current + 1
    worker.record_version = next_version
    worker.updated_at_utc = _now()
    item = WorkerProfileVersionModel(
        version_id=str(uuid.uuid4()),
        worker_id=worker_id,
        version_number=next_version,
        change_type=change_type,
        snapshot_json="",
        # Keep only the compact list of fields that changed. The full worker
        # snapshot is represented by relational history rows below.
        changed_fields_json=json.dumps(sorted(set(changed_fields or []))),
        source_system=source_system,
        source_file=source_file,
        source_checksum=source_checksum,
        source_record_key=source_record_key,
        actor=actor,
        created_at_utc=_now(),
    )
    session.add(item)
    session.flush()
    values = {
        "first_name": worker.first_name,
        "last_name": worker.last_name,
        "display_name": worker.display_name,
        "canonical_email": worker.canonical_email,
        "status": worker.status,
    }
    engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id)).all()
    for engagement in engagements:
        prefix = f"engagement.{engagement.source_system or 'UNKNOWN'}"
        values.update({
            f"{prefix}.vendor_name": engagement.vendor_name,
            f"{prefix}.program": engagement.program,
            f"{prefix}.project": engagement.project,
            f"{prefix}.lob": engagement.lob,
            f"{prefix}.job_title": engagement.job_title,
            f"{prefix}.supervisor_name": engagement.supervisor_name,
            f"{prefix}.country": engagement.country,
            f"{prefix}.site_location": engagement.site_location,
            f"{prefix}.onboarding_date": engagement.onboarding_date,
            f"{prefix}.production_start_date": engagement.production_start_date,
            f"{prefix}.work_order_id": engagement.work_order_id,
            f"{prefix}.npn": engagement.npn,
            f"{prefix}.license_state": engagement.license_state,
            f"{prefix}.license_number": engagement.license_number,
            f"{prefix}.taxonomy_code": engagement.taxonomy_code,
            f"{prefix}.key_billable_function": engagement.key_billable_function,
            f"{prefix}.statement_of_work": engagement.statement_of_work,
            f"{prefix}.primary_contact_name": engagement.primary_contact_name,
            f"{prefix}.status": engagement.status,
        })
    requested_fields = set(changed_fields or [])
    if requested_fields:
        original_fields = set(requested_fields)
        requested_fields.update({
            {
                "resident_license_state": "license_state", "resident_license_number": "license_number",
                "taxonomy": "taxonomy_code", "worker_primary_contact": "primary_contact_name",
                "sponsor_name": "primary_contact_name", "accessnow_status": "status",
                "worker_status": "status", "fg_status": "status", "worker_start_date": "onboarding_date",
                "worker_end_date": "production_start_date", "sow_worker_role": "job_title",
            }.get(field, field)
            for field in original_fields
        })
        values = {
            field_key: value
            for field_key, value in values.items()
            if field_key in requested_fields or field_key.rsplit(".", 1)[-1] in requested_fields
        }
    for field_key, value in values.items():
        session.add(FactWorkerFieldHistoryModel(
            history_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"iam-automation:history:{item.version_id}:{field_key}")),
            worker_id=worker_id,
            source_system=source_system or "CANONICAL",
            field_key=field_key,
            value_text=str(value or ""),
            version_number=next_version,
            observed_at_utc=item.created_at_utc,
            source_file=source_file,
        ))
    return item


def version_dict(item: WorkerProfileVersionModel) -> dict[str, object]:
    try:
        snapshot = json.loads(item.snapshot_json)
    except json.JSONDecodeError:
        snapshot = {}
    try:
        changed_fields = json.loads(item.changed_fields_json)
    except json.JSONDecodeError:
        changed_fields = []
    return {"version_id": item.version_id, "version_number": item.version_number, "change_type": item.change_type, "snapshot": snapshot, "changed_fields": changed_fields, "source_system": item.source_system, "source_file": Path(item.source_file).name if item.source_file else "", "source_checksum": item.source_checksum, "source_record_key": item.source_record_key, "actor": item.actor, "created_at_utc": item.created_at_utc}


def backfill_missing_worker_versions(database_path: Path, *, actor: str = "runtime-bootstrap") -> int:
    """Create a baseline snapshot for workers created before history was enabled.

    This is intentionally additive and idempotent. It gives older databases a
    reviewable version 1 without rewriting source lineage or changing the
    canonical profile.
    """
    created = 0
    with orm_session(database_path) as session:
        existing_worker_ids = set(session.scalars(select(WorkerProfileVersionModel.worker_id)).all())
        worker_ids = [
            worker_id
            for worker_id in session.scalars(select(WorkerModel.worker_id)).all()
            if worker_id not in existing_worker_ids
        ]
        for worker_id in worker_ids:
            record_worker_version(
                session,
                worker_id,
                actor=actor,
                change_type="BASELINE_BACKFILL",
                changed_fields=[],
            )
            created += 1
    return created
#endfile
