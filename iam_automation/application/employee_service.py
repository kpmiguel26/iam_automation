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

    def list_workers(self, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "") -> list[EmployeeSummary]:
        """Return the full directory for internal callers and small datasets."""
        workers, _ = self.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, page=1, per_page=None)
        return workers

    def list_workers_page(self, *, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "", page: int = 1, per_page: int | None = 25) -> tuple[list[EmployeeSummary], int]:
        """Query only one directory page; filtering stays in SQLite."""
        search = search.strip()
        engagement = engagement.strip()
        page = max(1, int(page))
        if per_page is not None:
            per_page = max(1, min(int(per_page), 100))
        with orm_session(self.database_path) as session:
            filters = []
            if status != "ALL":
                filters.append(WorkerModel.status == status)
            if vendor != "ALL":
                filters.append(select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, WorkerEngagementModel.vendor_name == vendor).exists())
            if source != "ALL":
                filters.append(select(WorkerIdentifierModel.worker_id).where(WorkerIdentifierModel.worker_id == WorkerModel.worker_id, WorkerIdentifierModel.source_system == source, WorkerIdentifierModel.active.is_(True)).exists())
            if engagement:
                engagement_pattern = f"%{engagement}%"
                filters.append(select(WorkerEngagementModel.worker_id).where(
                    WorkerEngagementModel.worker_id == WorkerModel.worker_id,
                    or_(
                        WorkerEngagementModel.vendor_name.ilike(engagement_pattern),
                        WorkerEngagementModel.program.ilike(engagement_pattern),
                        WorkerEngagementModel.project.ilike(engagement_pattern),
                        WorkerEngagementModel.lob.ilike(engagement_pattern),
                        WorkerEngagementModel.job_title.ilike(engagement_pattern),
                        WorkerEngagementModel.country.ilike(engagement_pattern),
                        WorkerEngagementModel.site_location.ilike(engagement_pattern),
                        WorkerEngagementModel.statement_of_work.ilike(engagement_pattern),
                    ),
                ).exists())
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

    def filter_values(self) -> tuple[list[str], list[str], list[str]]:
        with orm_session(self.database_path) as session:
            statuses = sorted({value for value in session.scalars(select(WorkerModel.status)).all() if value})
            vendors = sorted({value for value in session.scalars(select(WorkerEngagementModel.vendor_name)).all() if value})
            sources = sorted({value for value in session.scalars(select(WorkerIdentifierModel.source_system).where(WorkerIdentifierModel.active.is_(True))).all() if value})
            return statuses, vendors, sources

    def list_staged_records(self) -> list[dict[str, str]]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS"))).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            return [{"record_id": row.record_id, "batch_id": row.batch_id, "source_system": row.source_system, "source_record_key": row.source_record_key, "source_file": Path(row.source_file).name, "status": row.status, "match_status": row.match_status, "matched_worker_id": row.matched_worker_id or "", "match_reason": row.match_reason, "payload": json.loads(row.normalized_json)} for row in rows]

    def request_previews(self, record_ids: list[str]) -> list[dict[str, object]]:
        """Return portable review data for a shared JSON approval request."""
        selected = {str(value) for value in record_ids if str(value).strip()}
        if not selected:
            return []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected)).order_by(IngestionRecordModel.row_number)).all()
            previews = []
            for row in rows:
                payload = json.loads(row.normalized_json)
                previews.append({
                    "record_id": row.record_id,
                    "source_record_key": row.source_record_key,
                    "source_system": row.source_system,
                    "source_file": Path(row.source_file).name,
                    "status": row.status,
                    "match_status": row.match_status,
                    "match_reason": row.match_reason,
                    "worker_name": " ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part),
                    "email": payload.get("email", ""),
                    "vendor": payload.get("vendor_name", "") or payload.get("statement_of_work", "").split(maxsplit=1)[0],
                    "identifier": payload.get("vendor_employee_id", "") or payload.get("supplier_reference", "") or payload.get("worker_id", ""),
                    "statement_of_work": payload.get("statement_of_work", ""),
                })
            return previews

    def resolve_import_record_ids(self, payload: dict[str, object]) -> list[str]:
        """Resolve shared request records on this workstation.

        UUIDs are local implementation identifiers and can differ when the
        same source workbook is ingested on another workstation. Prefer the
        UUID, then resolve portable previews by source system and source row
        key so a shared approval can be applied locally.
        """
        requested = {str(value) for value in payload.get("record_ids", []) if str(value).strip()}
        previews = payload.get("record_previews", [])
        portable_keys = {
            (str(item.get("source_system", "")), str(item.get("source_record_key", "")))
            for item in previews if isinstance(item, dict) and item.get("source_system") and item.get("source_record_key")
        }
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(requested))).all() if requested else []
            resolved = {row.record_id for row in rows}
            if portable_keys:
                candidates = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.source_system.in_({key[0] for key in portable_keys}))).all()
                resolved.update(row.record_id for row in candidates if (row.source_system, row.source_record_key) in portable_keys)
        return sorted(resolved)

    def apply_approved_import_records(self, record_ids: list[str], actor: str, *, request_payload: dict[str, object] | None = None) -> dict[str, object]:
        """Apply approved source records through their source-specific adapter."""
        from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter, SOURCE_SYSTEM

        if request_payload is not None:
            record_ids = self.resolve_import_record_ids(request_payload)
        with orm_session(self.database_path) as session:
            source_systems = set(session.scalars(select(IngestionRecordModel.source_system).where(IngestionRecordModel.record_id.in_(record_ids))).all())
        result: dict[str, object] = {"processed": 0, "created": 0, "reused": 0, "failed": 0, "errors": []}
        roster_ids = []
        rsr_ids = []
        for record_id in record_ids:
            with orm_session(self.database_path) as session:
                record = session.get(IngestionRecordModel, record_id)
                if record is None:
                    continue
                if record.source_system == SOURCE_SYSTEM:
                    rsr_ids.append(record_id)
                else:
                    roster_ids.append(record_id)
        if rsr_ids:
            rsr_result = RsrSupplierWorkerDetailsAdapter(self.database_path).apply_approved_records(rsr_ids, actor)
            result["processed"] = int(result["processed"]) + int(rsr_result["processed"])
            result["created"] = int(result["created"]) + int(rsr_result.get("created", 0))
            result["reused"] = int(result["reused"]) + int(rsr_result.get("reused", 0))
            result["failed"] = int(result["failed"]) + int(rsr_result["failed"])
            result["errors"] = list(result["errors"]) + list(rsr_result["errors"])
        if roster_ids:
            roster_result = self.promote_staged_records(roster_ids, actor)
            result["processed"] = int(result["processed"]) + int(roster_result["processed"])
            result["created"] = int(result["created"]) + int(roster_result["created"])
            result["reused"] = int(result["reused"]) + int(roster_result["reused"])
            result["failed"] = int(result["failed"]) + int(roster_result["failed"])
            result["errors"] = list(result["errors"]) + list(roster_result["errors"])
        return result

    def refresh_rsr_matches(self) -> dict[str, int]:
        """Refresh enrichment-source matching after canonical workers change."""
        from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter

        return RsrSupplierWorkerDetailsAdapter(self.database_path).refresh_matches()

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

    def source_update_preview(self, worker_id: str) -> dict[str, object] | None:
        """Return only pending source rows that affect one canonical worker.

        Source workbooks remain immutable evidence. This preview compares staged
        rows against the canonical worker and current engagement without
        promoting or mutating either record.
        """
        source_fields = {
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "canonical_email",
            "vendor_email": "canonical_email",
            "vendor_name": "vendor_name",
            "job_title": "job_title",
            "lob": "lob",
            "program": "program",
            "project": "project",
            "country": "country",
            "site_location": "site_location",
            "supervisor_name": "supervisor_name",
            "worker_start_date": "onboarding_date",
            "worker_end_date": "production_start_date",
            "worker_status": "engagement_status",
            "npn": "npn",
            "resident_license_state": "license_state",
            "resident_license_number": "license_number",
            "taxonomy": "taxonomy_code",
            "key_billable_function": "key_billable_function",
            "vendor_employee_id": "identifier_vendor_employee_id",
            "supplier_reference": "identifier_supplier_reference",
            "fieldglass_id": "identifier_fieldglass_id",
            "nuid": "identifier_nuid",
            "salesforce_id": "identifier_salesforce_id",
        }
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return None
            engagement = session.scalar(
                select(WorkerEngagementModel)
                .where(WorkerEngagementModel.worker_id == worker_id)
                .order_by(WorkerEngagementModel.updated_at_utc.desc())
            )
            identifiers = session.scalars(
                select(WorkerIdentifierModel)
                .where(WorkerIdentifierModel.worker_id == worker_id)
                .order_by(WorkerIdentifierModel.identifier_type)
            ).all()
            current = {
                "first_name": worker.first_name or "",
                "last_name": worker.last_name or "",
                "canonical_email": worker.canonical_email or "",
                **{
                    f"identifier_{item.identifier_type.lower()}": item.identifier_value or ""
                    for item in identifiers
                },
                **({
                    "vendor_name": engagement.vendor_name or "",
                    "job_title": engagement.job_title or "",
                    "lob": engagement.lob or "",
                    "program": engagement.program or "",
                    "project": engagement.project or "",
                    "country": engagement.country or "",
                    "site_location": engagement.site_location or "",
                    "supervisor_name": engagement.supervisor_name or "",
                    "onboarding_date": engagement.onboarding_date or "",
                    "production_start_date": engagement.production_start_date or "",
                    "engagement_status": engagement.status or "",
                    "npn": engagement.npn or "",
                    "license_state": engagement.license_state or "",
                    "license_number": engagement.license_number or "",
                    "taxonomy_code": engagement.taxonomy_code or "",
                    "key_billable_function": engagement.key_billable_function or "",
                } if engagement else {}),
            }
            rows = session.scalars(
                select(IngestionRecordModel)
                .where(
                    IngestionRecordModel.matched_worker_id == worker_id,
                    IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT")),
                )
                .order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number.desc())
            ).all()
            updates: list[dict[str, object]] = []
            seen: set[tuple[str, str, str]] = set()
            incoming_by_field: dict[str, dict[str, str]] = {}
            for row in rows:
                payload = json.loads(row.normalized_json)
                changes: list[dict[str, str]] = []
                for source_field, canonical_field in source_fields.items():
                    incoming = str(payload.get(source_field) or "").strip()
                    if not incoming:
                        continue
                    current_value = str(current.get(canonical_field) or "").strip()
                    incoming_by_field.setdefault(canonical_field, {
                        "incoming_value": incoming,
                        "source_field": source_field,
                        "source_system": row.source_system,
                        "source_file": Path(row.source_file).name,
                        "record_id": row.record_id,
                    })
                    if incoming.casefold() == current_value.casefold():
                        continue
                    key = (canonical_field, current_value.casefold(), incoming.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    changes.append({
                        "field": canonical_field,
                        "source_field": source_field,
                        "current_value": current_value,
                        "incoming_value": incoming,
                    })
                if changes:
                    updates.append({
                        "record_id": row.record_id,
                        "source_system": row.source_system,
                        "source_file": Path(row.source_file).name,
                        "source_record_key": row.source_record_key,
                        "source_checksum": row.source_checksum,
                        "row_number": row.row_number,
                        "match_status": row.match_status,
                        "changes": changes,
                    })
            fields: list[dict[str, object]] = []
            for field_name, current_value in current.items():
                incoming = incoming_by_field.get(field_name, {})
                incoming_value = str(incoming.get("incoming_value", ""))
                changed = bool(incoming_value) and incoming_value.casefold() != str(current_value).casefold()
                fields.append({
                    "field": field_name,
                    "current_value": str(current_value),
                    "incoming_value": incoming_value,
                    "changed": changed,
                    "source_field": incoming.get("source_field", ""),
                    "source_system": incoming.get("source_system", ""),
                    "source_file": incoming.get("source_file", ""),
                    "record_id": incoming.get("record_id", ""),
                })
            return {
                "worker_id": worker_id,
                "worker_name": worker.display_name,
                "updates": updates,
                "fields": fields,
                "new_employee_records": [],
            }

    def new_employee_source_preview(self) -> list[dict[str, object]]:
        """Return staged source rows that have no canonical worker match."""
        with orm_session(self.database_path) as session:
            rows = session.scalars(
                select(IngestionRecordModel)
                .where(
                    IngestionRecordModel.status.in_(("STAGED", "MATCHED", "UNMATCHED", "AMBIGUOUS", "CONFLICT")),
                    IngestionRecordModel.match_status.in_(("UNMATCHED", "AMBIGUOUS", "NOT_EVALUATED")),
                )
                .order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)
            ).all()
            result = []
            for row in rows:
                payload = json.loads(row.normalized_json)
                result.append({
                    "record_id": row.record_id,
                    "source_system": row.source_system,
                    "source_file": Path(row.source_file).name,
                    "source_record_key": row.source_record_key,
                    "match_status": row.match_status,
                    "match_reason": row.match_reason,
                    "worker_name": " ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part),
                    "email": payload.get("email", ""),
                    "identifier": payload.get("vendor_employee_id", "") or payload.get("supplier_reference", "") or payload.get("worker_id", ""),
                    "payload": payload,
                    "batch_id": row.batch_id,
                    "source_checksum": row.source_checksum,
                })
            return result

    def source_candidate_preview(self, record_id: str) -> dict[str, object] | None:
        """Return one unmatched source record for selective review."""
        with orm_session(self.database_path) as session:
            row = session.get(IngestionRecordModel, record_id)
            if row is None:
                return None
            payload = json.loads(row.normalized_json)
            return {
                "record_id": row.record_id,
                "batch_id": row.batch_id,
                "source_system": row.source_system,
                "source_file": Path(row.source_file).name,
                "source_record_key": row.source_record_key,
                "source_checksum": row.source_checksum,
                "status": row.status,
                "match_status": row.match_status,
                "match_reason": row.match_reason,
                "worker_name": " ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part),
                "payload": payload,
            }

    def source_update_overview(self) -> dict[str, object]:
        """Build the compact review worklist for the Employees area."""
        with orm_session(self.database_path) as session:
            worker_ids = session.scalars(
                select(IngestionRecordModel.matched_worker_id)
                .where(
                    IngestionRecordModel.matched_worker_id.is_not(None),
                    IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT")),
                )
                .distinct()
            ).all()
        existing = []
        for worker_id in worker_ids:
            preview = self.source_update_preview(str(worker_id))
            if preview and preview["updates"]:
                existing.append(preview)
        return {"existing_updates": existing, "new_employee_records": self.new_employee_source_preview()}

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
                statement_of_work=str(payload.get("statement_of_work") or ""),
                work_order_id=str(payload.get("work_order_id") or ""),
                primary_contact_name=str(payload.get("worker_primary_contact") or ""),
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
