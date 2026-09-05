"""Write governed source snapshots and facts for the star-schema transition."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ..infrastructure.sqlite.orm import (
    DimDateModel,
    DimFieldModel,
    DimSourceModel,
    FactAssignmentModel,
    FactSourceSnapshotModel,
    FactTerminationModel,
    FactWorkerFieldModel,
    ImportBatchModel,
    IngestionRecordModel,
    orm_session,
)
from .employee_field_projection_service import EmployeeFieldProjectionService


class StarSchemaWriter:
    """Add compact facts while legacy evidence remains available during transition."""

    @staticmethod
    def _id(prefix: str, value: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"iam-automation:{prefix}:{value}"))

    @classmethod
    def write_batch_in_session(cls, session, batch_id: str, now: str | None = None) -> int:
        observed_at = now or datetime.now(timezone.utc).isoformat()
        batch = session.get(ImportBatchModel, batch_id)
        if batch is None:
            return 0
        records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
        source_system = str(batch.source_type or "UNKNOWN").upper()
        source = session.scalar(select(DimSourceModel).where(DimSourceModel.source_system == source_system))
        if source is None:
            source = DimSourceModel(source_id=cls._id("source", source_system), source_system=source_system, label=source_system.replace("_", " ").title())
            session.add(source)
            session.flush()
        written = 0
        for record in records:
            payload = json.loads(record.normalized_json or "{}")
            snapshot = session.scalar(select(FactSourceSnapshotModel).where(
                FactSourceSnapshotModel.batch_id == batch_id,
                FactSourceSnapshotModel.source_id == source.source_id,
                FactSourceSnapshotModel.source_record_key == record.source_record_key,
            ))
            if snapshot is None:
                snapshot = FactSourceSnapshotModel(
                    snapshot_id=cls._id("snapshot", record.record_id), worker_id=record.matched_worker_id,
                    batch_id=batch_id, source_id=source.source_id, source_record_key=record.source_record_key,
                    observed_at_utc=observed_at, status="QUARANTINED" if record.status == "QUARANTINED" else "CURRENT",
                )
                session.add(snapshot)
                session.flush()
            else:
                snapshot.worker_id = record.matched_worker_id
                snapshot.status = "QUARANTINED" if record.status == "QUARANTINED" else "CURRENT"
            for field_key, raw_value in payload.items():
                field_key = str(field_key).strip().lower()
                if field_key not in EmployeeFieldProjectionService.PILOT_FIELDS:
                    continue
                field = session.scalar(select(DimFieldModel).where(DimFieldModel.field_key == field_key))
                if field is None:
                    field = DimFieldModel(field_id=cls._id("field", field_key), field_key=field_key, label=field_key.replace("_", " ").title())
                    session.add(field)
                    session.flush()
                value = session.scalar(select(FactWorkerFieldModel).where(FactWorkerFieldModel.snapshot_id == snapshot.snapshot_id, FactWorkerFieldModel.field_id == field.field_id))
                if value is None:
                    value = FactWorkerFieldModel(field_value_id=cls._id("field-value", f"{record.record_id}:{field_key}"), snapshot_id=snapshot.snapshot_id, worker_id=record.matched_worker_id, field_id=field.field_id)
                    session.add(value)
                value.worker_id = record.matched_worker_id
                value.value_text = str(raw_value or "").strip()
                written += 1
            cls._write_termination(session, snapshot, record, payload)
            cls._write_assignment(session, snapshot, record, payload)
        return written

    @staticmethod
    def clear_legacy_payloads(database_path, batch_id: str) -> None:
        """Remove per-row JSON after the star facts have been committed."""
        with orm_session(database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
            for record in records:
                if record.status != "QUARANTINED":
                    record.normalized_json = ""
                    record.payload_json = ""

    @classmethod
    def payload_for_record(cls, session, record) -> dict[str, str]:
        """Reconstruct a staged payload from star facts, with old-data fallback."""
        snapshot = session.get(FactSourceSnapshotModel, cls._id("snapshot", record.record_id))
        if snapshot is not None:
            rows = session.execute(
                select(DimFieldModel.field_key, FactWorkerFieldModel.value_text)
                .join(FactWorkerFieldModel, FactWorkerFieldModel.field_id == DimFieldModel.field_id)
                .where(FactWorkerFieldModel.snapshot_id == snapshot.snapshot_id)
            ).all()
            if rows:
                payload = {str(field_key): str(value or "") for field_key, value in rows}
                # Master Roster uses Employee Number as its stable source key.
                # Preserve that identifier even for batches projected before
                # employee_number was added to the compact field allow-list.
                if str(record.source_system) == "MASTER_ROSTER" and not payload.get("employee_number"):
                    payload["employee_number"] = str(record.source_record_key or "")
                return payload
        raw = record.normalized_json or record.payload_json or "{}"
        return json.loads(raw)

    @classmethod
    def link_record_in_session(cls, session, record, worker_id: str) -> None:
        """Attach star facts to the canonical employee after promotion."""
        snapshot = session.get(FactSourceSnapshotModel, cls._id("snapshot", record.record_id))
        if snapshot is None:
            return
        snapshot.worker_id = worker_id
        session.query(FactWorkerFieldModel).filter(FactWorkerFieldModel.snapshot_id == snapshot.snapshot_id).update({"worker_id": worker_id}, synchronize_session=False)
        session.query(FactTerminationModel).filter(FactTerminationModel.snapshot_id == snapshot.snapshot_id).update({"worker_id": worker_id}, synchronize_session=False)
        session.query(FactAssignmentModel).filter(FactAssignmentModel.snapshot_id == snapshot.snapshot_id).update({"worker_id": worker_id}, synchronize_session=False)

    @classmethod
    def _write_termination(cls, session, snapshot, record, payload: dict[str, object]) -> None:
        date_text = str(payload.get("terminated_date") or payload.get("termination_date") or "").strip()
        if not date_text:
            return
        event = session.scalar(select(FactTerminationModel).where(FactTerminationModel.snapshot_id == snapshot.snapshot_id))
        if event is None:
            event = FactTerminationModel(termination_id=cls._id("termination", record.record_id), snapshot_id=snapshot.snapshot_id, worker_id=record.matched_worker_id)
            session.add(event)
        event.worker_id = record.matched_worker_id
        event.termination_date = date_text
        event.termination_type = str(payload.get("termination_type") or payload.get("accessnow_status") or "").strip()

    @classmethod
    def _write_assignment(cls, session, snapshot, record, payload: dict[str, object]) -> None:
        if not any(str(payload.get(key) or "").strip() for key in ("work_order_id", "vendor_name", "job_title", "supervisor_name")):
            return
        assignment = session.scalar(select(FactAssignmentModel).where(FactAssignmentModel.snapshot_id == snapshot.snapshot_id))
        if assignment is None:
            assignment = FactAssignmentModel(assignment_id=cls._id("assignment", record.record_id), snapshot_id=snapshot.snapshot_id, worker_id=record.matched_worker_id)
            session.add(assignment)
        assignment.worker_id = record.matched_worker_id
        assignment.work_order_id = str(payload.get("work_order_id") or "").strip()
        assignment.job_title = str(payload.get("job_title") or "").strip()
        assignment.supervisor_name = str(payload.get("supervisor_name") or payload.get("manager_name") or "").strip()
