"""Write governed source snapshots and facts for the star-schema transition."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from .orm import (
    BridgeEmployeeIdentifierModel,
    DimEmployeeModel,
    DimDateModel,
    DimFieldModel,
    DimSourceModel,
    FactAccessNowEmployeeModel,
    FactAssignmentModel,
    FactEmployeeFieldHistoryModel,
    FactEmployeeStatusEventModel,
    FactMasterRosterEmployeeModel,
    FactRosterLockAssignmentModel,
    FactRsrAssignmentModel,
    FactSourceFieldValueModel,
    FactSourceSnapshotModel,
    FactTerminationModel,
    FactWorkerFieldModel,
    ImportBatchModel,
    IngestionRecordModel,
    WorkerModel,
    orm_session,
)


class StarSchemaWriter:
    """Persist every non-empty source column as a relational source fact.

    The compact employee projection remains governed separately by
    ``EmployeeFieldProjectionService``. Source facts are intentionally wider:
    they are the lossless, queryable replacement for the per-row JSON payload
    used by imports and reconciliation.
    """

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
            previous = session.scalar(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == record.source_system,
                IngestionRecordModel.source_record_key == record.source_record_key,
                IngestionRecordModel.record_id != record.record_id,
                IngestionRecordModel.created_at_utc < record.created_at_utc,
            ).order_by(IngestionRecordModel.created_at_utc.desc()))
            previous_payload = cls.payload_for_record(session, previous) if previous is not None else {}
            # Keep each source snapshot as a delta. The complete source row is
            # reconstructed by payload_for_record from this delta plus prior
            # snapshots, while the fact table stores only new evidence.
            fact_payload = {
                field_key: raw_value
                for field_key, raw_value in payload.items()
                if str(raw_value or "").strip()
                and str(previous_payload.get(field_key) or "").strip().casefold() != str(raw_value).strip().casefold()
            }
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
            for field_key, raw_value in fact_payload.items():
                field_key = str(field_key).strip().lower()
                # Empty cells do not carry source information and would add
                # substantial row volume for wide workbooks. The field
                # dimension still records every populated column encountered.
                if not str(raw_value or "").strip():
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
            cls._write_separated_fact(session, source, batch, record, payload, observed_at)
        return written

    @classmethod
    def _write_separated_fact(cls, session, source, batch, record, payload: dict[str, object], observed_at: str) -> None:
        """Write the immutable typed fact for the source report."""
        if record.status == "QUARANTINED":
            return
        fact_id = cls._id("source-fact", record.record_id)
        common = {
            "employee_key": cls._existing_employee_key(session, record.matched_worker_id),
            "batch_id": batch.batch_id,
            "source_id": source.source_id,
            "source_record_key": record.source_record_key,
            "source_file": record.source_file,
            "source_checksum": record.source_checksum,
            "row_number": record.row_number,
            "observed_at_utc": observed_at,
        }
        source_system = str(record.source_system or batch.source_type).upper()
        model = None
        if source_system == "ACCESSNOW":
            model = FactAccessNowEmployeeModel(
                accessnow_fact_id=fact_id,
                **common,
                accessnow_employee_id=cls._text(payload.get("accessnow_employee_id")),
                accessnow_nuid=cls._text(payload.get("accessnow_nuid")),
                first_name=cls._text(payload.get("first_name")), last_name=cls._text(payload.get("last_name")),
                email=cls._text(payload.get("email")), vendor_name=cls._text(payload.get("vendor_name")),
                job_title=cls._text(payload.get("job_title")), manager_nuid=cls._text(payload.get("manager_nuid")),
                supervisor_name=cls._text(payload.get("supervisor_name")), sponsor_nuid=cls._text(payload.get("sponsor_nuid")),
                sponsor_name=cls._text(payload.get("sponsor_name")), accessnow_status=cls._text(payload.get("accessnow_status")),
                termination_date=cls._text(payload.get("termination_date") or payload.get("terminated_date")),
                onboarding_date=cls._text(payload.get("onboarding_date")), production_start_date=cls._text(payload.get("production_start_date")),
            )
        elif source_system == "MASTER_ROSTER":
            model = FactMasterRosterEmployeeModel(
                master_roster_fact_id=fact_id, **common,
                employee_number=cls._text(payload.get("employee_number")), nuid_login_id=cls._text(payload.get("nuid_login_id")),
                npn_login_id=cls._text(payload.get("npn_login_id")), first_name=cls._text(payload.get("first_name")),
                last_name=cls._text(payload.get("last_name")), email=cls._text(payload.get("email")), parent_client=cls._text(payload.get("parent_client")),
                client=cls._text(payload.get("client")), program=cls._text(payload.get("program")), project=cls._text(payload.get("project")),
                site_hr_location=cls._text(payload.get("site_hr_location")), supervisor_employee_number=cls._text(payload.get("supervisor_employee_number")),
                supervisor_name=cls._text(payload.get("supervisor_name")), job_code=cls._text(payload.get("job_code")), job_title=cls._text(payload.get("job_title")),
                hire_date=cls._text(payload.get("hire_date")), project_start_date=cls._text(payload.get("project_start_date")),
                production_start_date=cls._text(payload.get("production_start_date")), actual_termination_date=cls._text(payload.get("actual_termination_date")),
                term_reason=cls._text(payload.get("term_reason")), assignment_status=cls._text(payload.get("assignment_status")),
                user_principal_name=cls._text(payload.get("user_principal_name")),
            )
        elif source_system == "ROSTER_LOCK":
            model = FactRosterLockAssignmentModel(
                roster_lock_fact_id=fact_id, **common,
                vendor_name=cls._text(payload.get("vendor_name")), vendor_employee_id=cls._text(payload.get("vendor_employee_id")),
                first_name=cls._text(payload.get("first_name")), last_name=cls._text(payload.get("last_name")), email=cls._text(payload.get("email")),
                job_title=cls._text(payload.get("job_title")), supervisor_name=cls._text(payload.get("supervisor_name")),
                onboarding_date=cls._text(payload.get("onboarding_date")), production_start_date=cls._text(payload.get("production_start_date")),
                assignment_status=cls._text(payload.get("assignment_status") or payload.get("status")), work_order_id=cls._text(payload.get("work_order_id")),
            )
        elif source_system == "RSR_SUPPLIER_WORKER_DETAILS":
            model = FactRsrAssignmentModel(
                rsr_fact_id=fact_id, **common,
                supplier_reference=cls._text(payload.get("supplier_reference")), worker_id=cls._text(payload.get("worker_id")),
                buyer_reference=cls._text(payload.get("buyer_reference")), work_order_id=cls._text(payload.get("work_order_id")),
                worker=cls._text(payload.get("worker")), first_name=cls._text(payload.get("first_name")), last_name=cls._text(payload.get("last_name")),
                email=cls._text(payload.get("email")), vendor_name=cls._text(payload.get("vendor_name")), worker_status=cls._text(payload.get("worker_status")),
                worker_start_date=cls._text(payload.get("worker_start_date")), worker_end_date=cls._text(payload.get("worker_end_date")),
                job_title=cls._text(payload.get("job_title")), supervisor_name=cls._text(payload.get("supervisor_name")),
                statement_of_work=cls._text(payload.get("statement_of_work")), supplier_name=cls._text(payload.get("supplier_name")),
            )
        if model is not None and session.get(type(model), fact_id) is None:
            session.add(model)

    @staticmethod
    def _text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _existing_employee_key(session, worker_id: str | None) -> str | None:
        if not worker_id:
            return None
        return str(worker_id) if session.get(DimEmployeeModel, str(worker_id)) is not None else None

    @classmethod
    def ensure_target_employee(cls, session, employee_key: str, payload: dict[str, object], now: str) -> DimEmployeeModel:
        employee = session.get(DimEmployeeModel, employee_key)
        worker = session.get(WorkerModel, employee_key)
        if employee is None:
            employee = DimEmployeeModel(employee_key=employee_key, first_name=cls._text(payload.get("first_name")), last_name=cls._text(payload.get("last_name")), display_name=" ".join(part for part in (cls._text(payload.get("first_name")), cls._text(payload.get("last_name"))) if part), canonical_email=cls._text(payload.get("email")).lower(), created_at_utc=now, updated_at_utc=now)
            if worker is not None:
                employee.first_name = worker.first_name
                employee.last_name = worker.last_name
                employee.display_name = worker.display_name
                employee.canonical_email = worker.canonical_email
            session.add(employee)
        else:
            employee.updated_at_utc = now
        return employee

    @classmethod
    def add_accessnow_identifiers(cls, session, employee_key: str, source: DimSourceModel, payload: dict[str, object], record_id: str, now: str) -> None:
        identifiers = (("ACCESSNOW_EMPLOYEE_ID", payload.get("accessnow_employee_id")), ("ACCESSNOW_NUID", payload.get("accessnow_nuid")), ("EMAIL", payload.get("email")))
        for identifier_type, value in identifiers:
            normalized = cls._text(value).casefold()
            if not normalized:
                continue
            exists = session.scalar(select(BridgeEmployeeIdentifierModel).where(BridgeEmployeeIdentifierModel.source_system == source.source_system, BridgeEmployeeIdentifierModel.identifier_type == identifier_type, BridgeEmployeeIdentifierModel.normalized_value == normalized))
            if exists is None:
                session.add(BridgeEmployeeIdentifierModel(employee_identifier_key=cls._id("employee-identifier", f"{source.source_system}:{identifier_type}:{normalized}"), employee_key=employee_key, source_id=source.source_id, source_system=source.source_system, identifier_type=identifier_type, identifier_value=cls._text(value), normalized_value=normalized, source_record_id=record_id, created_at_utc=now))

    @classmethod
    def add_accessnow_status_event(cls, session, employee_key: str, record, payload: dict[str, object], now: str) -> None:
        status = cls._text(payload.get("accessnow_status"))
        if not status:
            return
        source = session.scalar(select(DimSourceModel).where(DimSourceModel.source_system == "ACCESSNOW"))
        fact = session.get(FactAccessNowEmployeeModel, cls._id("source-fact", record.record_id))
        if source is None or fact is None:
            return
        event_id = cls._id("status-event", record.record_id)
        if session.get(FactEmployeeStatusEventModel, event_id) is None:
            session.add(FactEmployeeStatusEventModel(status_event_id=event_id, employee_key=employee_key, accessnow_fact_id=fact.accessnow_fact_id, source_id=source.source_id, source_record_id=record.record_id, status_code=status, effective_date=cls._text(payload.get("termination_date") or payload.get("terminated_date") or payload.get("deactivated_date")), owner_source_system="ACCESSNOW", observed_at_utc=now, created_at_utc=now))

    @classmethod
    def append_employee_field_history(cls, session, employee: DimEmployeeModel, source: DimSourceModel, record_id: str, now: str) -> None:
        """Append changed canonical values and retain only the newest three."""
        fields = {
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "display_name": employee.display_name,
            "canonical_email": employee.canonical_email,
        }
        for field_key, value in fields.items():
            text_value = cls._text(value)
            if not text_value:
                continue
            field = session.scalar(select(DimFieldModel).where(DimFieldModel.field_key == field_key))
            if field is None:
                field = DimFieldModel(field_id=cls._id("field", field_key), field_key=field_key, label=field_key.replace("_", " ").title())
                session.add(field)
                session.flush()
            latest = session.scalar(select(FactEmployeeFieldHistoryModel).where(FactEmployeeFieldHistoryModel.employee_key == employee.employee_key, FactEmployeeFieldHistoryModel.field_id == field.field_id).order_by(FactEmployeeFieldHistoryModel.version_number.desc()))
            if latest is not None and latest.value_text.casefold() == text_value.casefold():
                continue
            next_version = (latest.version_number + 1) if latest is not None else 1
            session.add(FactEmployeeFieldHistoryModel(history_id=cls._id("employee-history", f"{employee.employee_key}:{field_key}:{next_version}"), employee_key=employee.employee_key, field_id=field.field_id, owner_source_id=source.source_id, source_record_id=record_id, value_text=text_value, version_number=next_version, observed_at_utc=now, created_at_utc=now))
            session.flush()
            history = session.scalars(select(FactEmployeeFieldHistoryModel).where(FactEmployeeFieldHistoryModel.employee_key == employee.employee_key, FactEmployeeFieldHistoryModel.field_id == field.field_id).order_by(FactEmployeeFieldHistoryModel.version_number.desc())).all()
            for old in history[3:]:
                session.delete(old)

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
        if record is None:
            return {}
        snapshot = session.get(FactSourceSnapshotModel, cls._id("snapshot", record.record_id))
        if snapshot is not None:
            rows = session.execute(
                select(DimFieldModel.field_key, FactWorkerFieldModel.value_text)
                .join(FactWorkerFieldModel, FactWorkerFieldModel.field_id == DimFieldModel.field_id)
                .where(FactWorkerFieldModel.snapshot_id == snapshot.snapshot_id)
            ).all()
            payload = {}
            previous = session.scalar(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == record.source_system,
                IngestionRecordModel.source_record_key == record.source_record_key,
                IngestionRecordModel.record_id != record.record_id,
                IngestionRecordModel.created_at_utc < record.created_at_utc,
            ).order_by(IngestionRecordModel.created_at_utc.desc()))
            if previous is not None:
                payload.update(cls.payload_for_record(session, previous))
            payload.update({str(field_key): str(value or "") for field_key, value in rows})
            # Master Roster uses Employee Number as its stable source key.
            # Preserve that identifier even for delta snapshots that did not
            # need to repeat the key.
            if str(record.source_system) == "MASTER_ROSTER" and not payload.get("employee_number"):
                payload["employee_number"] = str(record.source_record_key or "")
            if payload:
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
