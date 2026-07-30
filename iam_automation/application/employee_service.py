from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, or_, select

from ..infrastructure.sqlite.orm import (
    IngestionRecordModel,
    WorkerDiscrepancyModel,
    WorkerEngagementModel,
    WorkerIdentifierModel,
    WorkerModel,
    WorkerSourceLineageModel,
    orm_session,
)


@dataclass(frozen=True)
class EmployeeSummary:
    worker_id: str
    display_name: str
    email: str
    status: str
    identifier: str
    vendor_name: str
    job_title: str
    source_system: str
    discrepancy_count: int


class EmployeeService:
    """Read canonical workers and explicitly promote staged source records."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_workers(self, search: str = "", status: str = "ALL", vendor: str = "ALL") -> list[EmployeeSummary]:
        """Return the full directory for internal callers and small datasets."""
        workers, _ = self.list_workers_page(search=search, status=status, vendor=vendor, page=1, per_page=None)
        return workers

    def list_workers_page(self, *, search: str = "", status: str = "ALL", vendor: str = "ALL", page: int = 1, per_page: int | None = 25) -> tuple[list[EmployeeSummary], int]:
        """Query only one directory page; filtering stays in SQLite."""
        search = search.strip()
        page = max(1, int(page))
        if per_page is not None:
            per_page = max(1, min(int(per_page), 100))
        with orm_session(self.database_path) as session:
            filters = []
            if status != "ALL":
                filters.append(WorkerModel.status == status)
            if vendor != "ALL":
                filters.append(select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, WorkerEngagementModel.vendor_name == vendor).exists())
            if search:
                pattern = f"%{search}%"
                filters.append(or_(
                    WorkerModel.display_name.ilike(pattern),
                    WorkerModel.canonical_email.ilike(pattern),
                    select(WorkerIdentifierModel.worker_id).where(WorkerIdentifierModel.worker_id == WorkerModel.worker_id, WorkerIdentifierModel.identifier_value.ilike(pattern)).exists(),
                    select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, or_(WorkerEngagementModel.vendor_name.ilike(pattern), WorkerEngagementModel.job_title.ilike(pattern))).exists(),
                ))
            statement = select(WorkerModel).where(*filters).order_by(WorkerModel.display_name, WorkerModel.worker_id)
            total = int(session.scalar(select(func.count()).select_from(WorkerModel).where(*filters)) or 0)
            if per_page is not None:
                statement = statement.offset((page - 1) * per_page).limit(per_page)
            workers = session.scalars(statement).all()
            result: list[EmployeeSummary] = []
            for worker in workers:
                engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker.worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
                identifier = session.scalar(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker.worker_id, WorkerIdentifierModel.active.is_(True)).order_by(WorkerIdentifierModel.created_at_utc))
                discrepancy_count = session.scalar(select(func.count()).select_from(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id == worker.worker_id, WorkerDiscrepancyModel.status == "OPEN")) or 0
                result.append(EmployeeSummary(worker.worker_id, worker.display_name, worker.canonical_email, worker.status, identifier.identifier_value if identifier else "", engagement.vendor_name if engagement else "", engagement.job_title if engagement else "", identifier.source_system if identifier else "", int(discrepancy_count)))
            return result, total

    def filter_values(self) -> tuple[list[str], list[str]]:
        with orm_session(self.database_path) as session:
            statuses = sorted({value for value in session.scalars(select(WorkerModel.status)).all() if value})
            vendors = sorted({value for value in session.scalars(select(WorkerEngagementModel.vendor_name)).all() if value})
            return statuses, vendors

    def list_staged_records(self) -> list[dict[str, str]]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status.in_(("STAGED", "MATCHED"))).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            return [{"record_id": row.record_id, "batch_id": row.batch_id, "source_record_key": row.source_record_key, "source_file": Path(row.source_file).name, "status": row.status, "payload": json.loads(row.normalized_json)} for row in rows]

    def get_worker(self, worker_id: str) -> dict[str, object] | None:
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return None
            identifiers = session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker_id).order_by(WorkerIdentifierModel.source_system, WorkerIdentifierModel.identifier_type)).all()
            engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.created_at_utc.desc())).all()
            lineage = session.scalars(select(WorkerSourceLineageModel).where(WorkerSourceLineageModel.worker_id == worker_id).order_by(WorkerSourceLineageModel.observed_at_utc.desc()).limit(100)).all()
            discrepancies = session.scalars(select(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id == worker_id).order_by(WorkerDiscrepancyModel.created_at_utc.desc())).all()
            return {"worker": worker, "identifiers": identifiers, "engagements": engagements, "lineage": lineage, "discrepancies": discrepancies}

    def _promote_record_in_session(self, session, record: IngestionRecordModel, now: str) -> tuple[str, bool]:
        """Promote one record while the caller owns the transaction."""
        payload = json.loads(record.normalized_json)
        identifier_value = str(payload.get("vendor_employee_id") or "").strip()
        if not identifier_value:
            raise ValueError("The staged record has no Vendor Employee ID.")

        normalized_id = identifier_value.casefold()
        existing_identifier = session.scalar(
            select(WorkerIdentifierModel).where(
                WorkerIdentifierModel.source_system == "ROSTER_LOCK",
                WorkerIdentifierModel.identifier_type == "VENDOR_EMPLOYEE_ID",
                WorkerIdentifierModel.normalized_value == normalized_id,
            )
        )
        created = existing_identifier is None
        if existing_identifier:
            worker_id = existing_identifier.worker_id
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                raise ValueError("The staged record references a missing canonical worker.")
        else:
            worker_id = str(uuid.uuid4())
            first_name = str(payload.get("first_name") or "").strip()
            last_name = str(payload.get("last_name") or "").strip()
            worker = WorkerModel(
                worker_id=worker_id,
                first_name=first_name,
                last_name=last_name,
                display_name=" ".join(part for part in (first_name, last_name) if part),
                canonical_email=str(payload.get("email") or "").strip().lower(),
                status="PENDING",
                record_version=1,
                created_at_utc=now,
                updated_at_utc=now,
            )
            session.add(worker)
            session.add(
                WorkerIdentifierModel(
                    identifier_id=str(uuid.uuid4()),
                    worker_id=worker_id,
                    source_system="ROSTER_LOCK",
                    identifier_type="VENDOR_EMPLOYEE_ID",
                    identifier_value=identifier_value,
                    normalized_value=normalized_id,
                    confidence="HIGH",
                    created_at_utc=now,
                )
            )

        engagement_id = str(uuid.uuid4())
        session.add(
            WorkerEngagementModel(
                engagement_id=engagement_id,
                worker_id=worker_id,
                vendor_name=str(payload.get("vendor_name") or ""),
                program=str(payload.get("program") or ""),
                project=str(payload.get("project") or ""),
                lob=str(payload.get("lob") or ""),
                supervisor_name=str(payload.get("supervisor_name") or ""),
                job_title=str(payload.get("job_title") or ""),
                country=str(payload.get("country") or ""),
                site_location=str(payload.get("site_location") or ""),
                onboarding_date=str(payload.get("onboarding_date") or ""),
                production_start_date=str(payload.get("production_start_date") or ""),
                status=str(payload.get("status") or "PENDING"),
                npn=str(payload.get("npn") or ""),
                license_state=str(payload.get("resident_license_state") or ""),
                license_number=str(payload.get("resident_license_number") or ""),
                taxonomy_code=str(payload.get("taxonomy_code") or ""),
                key_billable_function=str(payload.get("key_billable_function") or ""),
                source_system=record.source_system,
                created_at_utc=now,
                updated_at_utc=now,
            )
        )
        for field_name, value in payload.items():
            session.add(
                WorkerSourceLineageModel(
                    lineage_id=str(uuid.uuid4()),
                    worker_id=worker_id,
                    engagement_id=engagement_id,
                    batch_id=record.batch_id,
                    source_system=record.source_system,
                    source_file=record.source_file,
                    source_checksum=record.source_checksum,
                    row_number=record.row_number,
                    field_name=field_name,
                    raw_value=str(value or ""),
                    normalized_value=str(value or ""),
                    observed_at_utc=now,
                )
            )
        record.status = "MATCHED"
        return worker_id, created

    def promote_all_staged_records(self, actor: str) -> dict[str, object]:
        """Promote all pending staged records in one transaction.

        A malformed row is reported in the result and does not prevent the
        valid rows from being promoted. The transaction is committed once at
        the end so the web application never performs one request per worker.
        """
        del actor  # The caller owns the audit event for this bulk operation.
        now = datetime.now(timezone.utc).isoformat()
        errors: list[dict[str, str]] = []
        processed = created = reused = 0
        with orm_session(self.database_path) as session:
            records = session.scalars(
                select(IngestionRecordModel)
                .where(IngestionRecordModel.status == "STAGED")
                .order_by(IngestionRecordModel.created_at_utc, IngestionRecordModel.row_number)
            ).all()
            for record in records:
                try:
                    _, was_created = self._promote_record_in_session(session, record, now)
                    processed += 1
                    if was_created:
                        created += 1
                    else:
                        reused += 1
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "source_record_key": record.source_record_key, "error": str(exc)})
            session.commit()
        return {"processed": processed, "created": created, "reused": reused, "failed": len(errors), "errors": errors}

    def promote_staged_records(self, record_ids: list[str], actor: str) -> dict[str, object]:
        """Apply only the records approved by an import request."""
        del actor
        selected_ids = {str(record_id) for record_id in record_ids if str(record_id).strip()}
        if not selected_ids:
            raise ValueError("The import request contains no staged records.")
        now = datetime.now(timezone.utc).isoformat()
        processed = created = reused = 0
        errors: list[dict[str, str]] = []
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected_ids))).all()
            for record in records:
                if record.status != "STAGED":
                    errors.append({"record_id": record.record_id, "error": f"Record is no longer staged: {record.status}."})
                    continue
                try:
                    _, was_created = self._promote_record_in_session(session, record, now)
                    processed += 1
                    created += int(was_created)
                    reused += int(not was_created)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "error": str(exc)})
            session.commit()
        return {"processed": processed, "created": created, "reused": reused, "failed": len(errors), "errors": errors}

    def promote_ingestion_record(self, record_id: str, actor: str) -> str:
        """Create a pending worker and engagement from one staged record.

        This is explicit and reversible through the normal review/publication flow;
        the file watcher never calls it automatically.
        """
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            record = session.get(IngestionRecordModel, record_id)
            if record is None:
                raise ValueError("Ingestion record was not found.")
            if record.status not in {"STAGED", "MATCHED"}:
                raise ValueError(f"Ingestion record cannot be promoted from status {record.status}.")
            worker_id, _ = self._promote_record_in_session(session, record, now)
            return worker_id
