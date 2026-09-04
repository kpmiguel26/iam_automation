"""
File: iam_automation/application/accessnow_ingestion_service.py
Purpose: Implements the application service for accessnow ingestion service workflows.
Responsibilities: Exposes or coordinates: AccessNowIngestionResult, AccessNowIngestionService.
Dependencies: sqlalchemy, infrastructure, publication_state, source_reconciliation, worker_history_service
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import (
    ImportBatchModel,
    IngestionRecordModel,
    QuarantineRecordModel,
    WorkerEngagementModel,
    WorkerIdentifierModel,
    WorkerModel,
    WorkerSourceLineageModel,
    orm_session,
)
from .publication_state import mark_publication_pending
from .source_reconciliation import _match_types, ensure_source_identifiers, find_worker_matches, reconcile_worker_status_in_session, source_identifiers
from .worker_history_service import record_worker_version
from .stable_file_read import file_modified_at_utc, read_stable_bytes
from .star_schema_writer import StarSchemaWriter
from .status_catalog import normalize_accessnow_status, status_rank
from .ingestion_dedup import latest_payload_digests, payload_digest, serialize_payload


SOURCE_SYSTEM = "ACCESSNOW"


@dataclass(frozen=True)
class AccessNowIngestionResult:
    batch_id: str
    filename: str
    source_checksum: str
    total_rows: int
    staged_rows: int
    quarantine_rows: int
    already_processed: bool = False


class AccessNowIngestionService:
    """Stage the AccessNow active and termination reports as one source view."""

    SOURCE_SYSTEM = SOURCE_SYSTEM
    MERGE_SCHEMA_VERSION = "ACCESSNOW_MERGE_V2"

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def ingest_folder(self, folder: Path) -> AccessNowIngestionResult:
        folder = folder.expanduser().resolve()
        paths = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"} and not path.name.startswith("."))
        if not paths:
            raise ValueError("The AccessNow folder has no CSV or XLSX files.")
        contents = {path: read_stable_bytes(path) for path in paths}
        source_checksum = hashlib.sha256(self.MERGE_SCHEMA_VERSION.encode() + b"\0" + b"".join(path.name.encode() + b"\0" + contents[path] for path in paths)).hexdigest()
        source_file = "; ".join(path.name for path in paths)
        source_modified_at = max((file_modified_at_utc(path) for path in paths), default="")
        with orm_session(self.database_path) as session:
            existing = session.scalar(select(IngestionRecordModel).where(IngestionRecordModel.source_system == SOURCE_SYSTEM, IngestionRecordModel.source_checksum == source_checksum))
            if existing:
                batch = session.get(ImportBatchModel, existing.batch_id)
                return AccessNowIngestionResult(existing.batch_id, source_file, source_checksum, batch.total_rows if batch else 0, batch.valid_rows if batch else 0, batch.quarantine_rows if batch else 0, True)

        merged: dict[str, tuple[Path, int, dict[str, str]]] = {}
        total_rows = 0
        for path in paths:
            for row_number, raw in self._read_rows(path, contents[path]):
                total_rows += 1
                payload = self._normalize(raw)
                key = payload.get("accessnow_employee_id", "")
                if not key:
                    key = f"ROW:{path.name}:{row_number}"
                current = merged.get(key)
                if current is None:
                    merged[key] = (path, row_number, payload)
                else:
                    # Merge the two reports field by field. The termination
                    # status wins, but an otherwise sparse termination row
                    # must not discard email, dates, manager, or sponsor data
                    # supplied by the active report.
                    current_payload = current[2]
                    current_rank = status_rank(current_payload.get("accessnow_status", ""))
                    incoming_rank = status_rank(payload.get("accessnow_status", ""))
                    for field_name, incoming_value in payload.items():
                        if not current_payload.get(field_name) or (incoming_rank > current_rank and field_name in {"accessnow_status", "terminated_date"}):
                            current_payload[field_name] = incoming_value

        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        staged = quarantined = 0
        seen: set[str] = set()
        with orm_session(self.database_path) as session:
            existing_source_rows = {
                (str(source_file), str(checksum), int(row_number))
                for source_file, checksum, row_number in session.execute(
                    select(IngestionRecordModel.source_file, IngestionRecordModel.source_checksum, IngestionRecordModel.row_number).where(
                        IngestionRecordModel.source_system == SOURCE_SYSTEM,
                        IngestionRecordModel.source_checksum == source_checksum,
                    )
                ).all()
            }
            session.add(ImportBatchModel(batch_id=batch_id, filename=source_file, source_type=SOURCE_SYSTEM, status="PROCESSING", total_rows=total_rows, valid_rows=0, quarantine_rows=0, created_by="workspace-watcher", created_at_utc=now, source_modified_at_utc=source_modified_at))
            existing_payloads = latest_payload_digests(session, SOURCE_SYSTEM, {str(payload.get("accessnow_employee_id", "")) for _, _, payload in merged.values()})
            for row_number, (path, original_row, payload) in enumerate(merged.values(), start=2):
                source_row_key = (str(path), source_checksum, int(original_row))
                if source_row_key in existing_source_rows:
                    # A previous watcher run may have committed the rows but
                    # failed before publishing the batch marker. The unique
                    # source-row constraint makes retrying that folder fail;
                    # retain the existing evidence and continue with new rows.
                    continue
                source_key = payload.get("accessnow_employee_id", "")
                normalized_json = serialize_payload(payload)
                if source_key and source_key not in seen and existing_payloads.get(source_key) == payload_digest(normalized_json):
                    continue
                reason = self._validation_error(payload, source_key, seen)
                if reason:
                    quarantined += 1
                    session.add(QuarantineRecordModel(quarantine_id=str(uuid.uuid4()), batch_id=batch_id, row_number=row_number, reason=reason, payload_json=json.dumps(payload, sort_keys=True), status="OPEN", created_at_utc=now))
                    continue
                seen.add(source_key)
                staged += 1
                session.add(IngestionRecordModel(record_id=str(uuid.uuid4()), batch_id=batch_id, source_system=SOURCE_SYSTEM, source_file=str(path), source_checksum=source_checksum, row_number=original_row, source_record_key=source_key, normalized_json=normalized_json, payload_json=json.dumps(payload, sort_keys=True), status="STAGED", created_at_utc=now))
            session.flush()
            match_index = self._build_match_index(session)
            for record in session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id, IngestionRecordModel.source_system == SOURCE_SYSTEM)).all():
                matches, reason = self._find_match_detail(session, json.loads(record.normalized_json), match_index)
                if len(matches) == 1:
                    record.matched_worker_id = matches[0]
                    record.match_status = "MATCHED"
                    record.match_reason = reason
                elif len(matches) > 1:
                    record.match_status = "AMBIGUOUS"
                    record.match_reason = "AccessNow identifiers resolve to multiple canonical employees."
                else:
                    record.match_status = "UNMATCHED"
                    record.match_reason = "No canonical employee match; approved creation is available."
            StarSchemaWriter.write_batch_in_session(session, batch_id, now)
            batch = session.get(ImportBatchModel, batch_id)
            batch.valid_rows = staged
            batch.quarantine_rows = quarantined
            batch.status = "COMPLETED" if quarantined == 0 else "COMPLETED_WITH_WARNINGS"
            batch.completed_at_utc = datetime.now(timezone.utc).isoformat()
        return AccessNowIngestionResult(batch_id, source_file, source_checksum, total_rows, staged, quarantined)

    @staticmethod
    def _build_match_index(session) -> dict[str, dict[tuple[str, str], set[str]]]:
        """Load reconciliation keys once for a high-volume AccessNow batch."""
        active_workers = {
            str(worker_id)
            for worker_id, superseded_by in session.execute(
                select(WorkerModel.worker_id, WorkerModel.superseded_by_worker_id)
            ).all()
            if not superseded_by
        }
        identifiers: dict[tuple[str, str], set[str]] = {}
        for identifier_type, normalized_value, worker_id in session.execute(
            select(WorkerIdentifierModel.identifier_type, WorkerIdentifierModel.normalized_value, WorkerIdentifierModel.worker_id).where(
                WorkerIdentifierModel.active.is_(True)
            )
        ).all():
            if str(worker_id) in active_workers:
                identifiers.setdefault((str(identifier_type), str(normalized_value).casefold()), set()).add(str(worker_id))

        emails: dict[str, set[str]] = {}
        names: dict[tuple[str, str], set[str]] = {}
        for worker_id, email, first_name, last_name, superseded_by in session.execute(
            select(WorkerModel.worker_id, WorkerModel.canonical_email, WorkerModel.first_name, WorkerModel.last_name, WorkerModel.superseded_by_worker_id)
        ).all():
            if superseded_by:
                continue
            worker_key = str(worker_id)
            if email:
                emails.setdefault(str(email).casefold(), set()).add(worker_key)
            if first_name and last_name:
                names.setdefault((str(first_name).casefold(), str(last_name).casefold()), set()).add(worker_key)
        return {"identifiers": identifiers, "emails": emails, "names": names}

    @staticmethod
    def _find_match_detail(session, payload: dict[str, str], match_index: dict[str, dict[tuple[str, str], set[str]]] | None = None) -> tuple[list[str], str]:
        if match_index is None:
            return find_worker_matches(session, SOURCE_SYSTEM, payload)
        strong_matches: dict[str, set[str]] = {}
        identifiers = match_index["identifiers"]
        for identifier_type, value in source_identifiers(SOURCE_SYSTEM, payload):
            if identifier_type in {"ACCESSNOW_MANAGER_NUID", "ACCESSNOW_SPONSOR_NUID", "WORK_ORDER_ID"}:
                continue
            for alias in _match_types(SOURCE_SYSTEM, identifier_type):
                for worker_id in identifiers.get((alias, value.casefold()), set()):
                    strong_matches.setdefault(worker_id, set()).add(identifier_type)
        if strong_matches:
            if len(strong_matches) == 1:
                return sorted(strong_matches), "Exact source identifier match"
            return sorted(strong_matches), "Conflicting source identifiers"
        email = str(payload.get("email") or payload.get("vendor_email") or payload.get("vendor_email_address") or "").strip().casefold()
        if email and (matches := match_index["emails"].get(email)):
            return sorted(matches), "Canonical email match"
        first = str(payload.get("first_name") or payload.get("employee_first_name") or "").strip().casefold()
        last = str(payload.get("last_name") or payload.get("employee_last_name") or "").strip().casefold()
        if first and last and (matches := match_index["names"].get((first, last))):
            return sorted(matches), "Canonical name match"
        return [], "No canonical match"

    @staticmethod
    def _read_rows(path: Path, content: bytes) -> list[tuple[int, dict[str, object]]]:
        if path.suffix.lower() == ".csv":
            text = content.decode("utf-8-sig", errors="replace")
            return [(number, dict(row)) for number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2)]
        try:
            from openpyxl import load_workbook
        except ModuleNotFoundError as exc:
            raise RuntimeError("AccessNow XLSX ingestion requires openpyxl.") from exc
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            values = list(workbook.active.values)
            if not values:
                return []
            headers = [str(value or "").strip() for value in values[0]]
            return [(number, dict(zip(headers, row))) for number, row in enumerate(values[1:], start=2) if any(value not in (None, "") for value in row)]
        finally:
            workbook.close()

    @classmethod
    def _normalize(cls, raw: dict[str, object]) -> dict[str, str]:
        values = {cls._key(key): cls._value(value) for key, value in raw.items() if key}
        aliases = {
            "employee_id": "accessnow_employee_id", "nuid": "accessnow_nuid", "first_name": "first_name", "last_name": "last_name",
            "kp_email": "email", "employee_status": "accessnow_status", "company_name": "vendor_name", "workforce_class": "job_title",
            "kp_start_date": "onboarding_date", "kp_sunset_date": "production_start_date", "terminated_date": "terminated_date",
            "manager_nuid": "manager_nuid", "manager_name": "supervisor_name", "sponsor_nuid": "sponsor_nuid", "sponsor_name": "sponsor_name",
            "kp_create_date": "created_date",
        }
        normalized = {aliases.get(key, key): value.strip() for key, value in values.items() if value.strip()}
        normalized["accessnow_status"] = cls._normalize_status(normalized.get("accessnow_status", ""))
        return normalized

    @staticmethod
    def _key(value: object) -> str:
        return "_".join("".join(char.lower() if char.isalnum() else " " for char in str(value)).split())

    @staticmethod
    def _value(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_status(value: object) -> str:
        return normalize_accessnow_status(value)

    @classmethod
    def _status_rank(cls, status: str) -> int:
        return status_rank(status)

    @staticmethod
    def _validation_error(payload: dict[str, str], source_key: str, seen: set[str]) -> str:
        if not payload.get("accessnow_employee_id"):
            return "Missing Employee ID."
        if source_key in seen:
            return "Duplicate Employee ID after active/termination merge."
        if not payload.get("first_name") and not payload.get("last_name"):
            return "Missing employee name."
        if not payload.get("accessnow_status"):
            return "Missing Employee status."
        return ""

    def apply_approved_records(
        self,
        record_ids: list[str],
        actor: str,
        *,
        progress_callback: Callable[[int, int, int, int, int], None] | None = None,
    ) -> dict[str, object]:
        selected = {str(value) for value in record_ids if str(value).strip()}
        if not selected:
            raise ValueError("The AccessNow import request contains no records.")
        now = datetime.now(timezone.utc).isoformat()
        processed = created = reused = failed = 0
        errors: list[dict[str, str]] = []
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected), IngestionRecordModel.source_system == SOURCE_SYSTEM)).all()
            handled = 0
            for record in records:
                if record.status == "APPLIED":
                    reused += 1
                    handled += 1
                    if progress_callback:
                        progress_callback(handled, len(records), created, reused, failed)
                    continue
                if record.status != "STAGED" or record.match_status not in {"MATCHED", "UNMATCHED"}:
                    errors.append({"record_id": record.record_id, "error": f"Record is not eligible: {record.status}/{record.match_status}."})
                    failed += 1
                    handled += 1
                    if progress_callback:
                        progress_callback(handled, len(records), created, reused, failed)
                    continue
                try:
                    payload = json.loads(record.normalized_json)
                    worker_id = record.matched_worker_id
                    # AccessNow files can be staged before the preceding
                    # sources are imported. Re-evaluate an unmatched record
                    # at apply time so a late canonical match does not become
                    # a duplicate employee.
                    if worker_id is None:
                        matches, reason = find_worker_matches(session, SOURCE_SYSTEM, payload)
                        if len(matches) > 1:
                            record.match_status = "AMBIGUOUS"
                            record.match_reason = "AccessNow identifiers resolve to multiple canonical employees."
                            raise ValueError(record.match_reason)
                        if len(matches) == 1:
                            worker_id = matches[0]
                            record.matched_worker_id = worker_id
                            record.match_status = "MATCHED"
                            record.match_reason = reason
                    was_created = worker_id is None
                    if was_created:
                        worker_id = str(uuid.uuid4())
                        session.add(WorkerModel(worker_id=worker_id, first_name=payload.get("first_name", ""), last_name=payload.get("last_name", ""), display_name=" ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part), canonical_email=payload.get("email", "").lower(), status="PENDING", record_version=1, created_at_utc=now, updated_at_utc=now))
                        created += 1
                    else:
                        reused += 1
                    worker = session.get(WorkerModel, worker_id)
                    old_status = worker.status
                    # AccessNow is an evidence source. It may populate a
                    # missing canonical value, but it must not replace a
                    # value already supplied by another source.
                    if not worker.first_name and payload.get("first_name"):
                        worker.first_name = payload["first_name"]
                    if not worker.last_name and payload.get("last_name"):
                        worker.last_name = payload["last_name"]
                    if not worker.canonical_email and payload.get("email"):
                        worker.canonical_email = payload["email"].lower()
                    worker.display_name = " ".join(part for part in (worker.first_name, worker.last_name) if part)
                    # Keep one immutable AccessNow observation engagement per
                    # applied batch instead of updating a prior observation.
                    engagement = WorkerEngagementModel(engagement_id=str(uuid.uuid4()), worker_id=worker_id, source_system=SOURCE_SYSTEM, created_at_utc=now, updated_at_utc=now)
                    session.add(engagement)
                    self._apply_engagement(engagement, payload, now)
                    self._add_identifiers(session, worker_id, payload, now)
                    for field_name, value in payload.items():
                        session.add(WorkerSourceLineageModel(lineage_id=str(uuid.uuid4()), worker_id=worker_id, engagement_id=engagement.engagement_id, batch_id=record.batch_id, source_system=SOURCE_SYSTEM, source_file=record.source_file, source_checksum=record.source_checksum, row_number=record.row_number, field_name=field_name, raw_value=str(value or ""), normalized_value=str(value or ""), observed_at_utc=now))
                    record.matched_worker_id = worker_id
                    record.match_status = "MATCHED"
                    reconcile_worker_status_in_session(session, worker_id)
                    changed = list(payload)
                    if old_status != worker.status and "status" not in changed:
                        changed.append("status")
                    record_worker_version(session, worker_id, actor=actor, change_type="ACCESSNOW_INITIAL_PROFILE" if was_created else "ACCESSNOW_STATUS_UPDATE", source_system=SOURCE_SYSTEM, source_file=record.source_file, source_checksum=record.source_checksum, source_record_key=record.source_record_key, changed_fields=changed)
                    if was_created:
                        record.match_reason = "Canonical employee created during approval"
                    elif not record.match_reason:
                        record.match_reason = "Canonical employee updated during approval"
                    record.status = "APPLIED"
                    record.observation_state = "CURRENT"
                    record.linked_at_utc = record.linked_at_utc or now
                    record.last_seen_at_utc = now
                    processed += 1
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "error": str(exc)})
                    failed += 1
                handled += 1
                if progress_callback:
                    progress_callback(handled, len(records), created, reused, failed)
            session.commit()
        if processed:
            mark_publication_pending(self.database_path, actor=actor, reason="AccessNow source update applied locally")
        return {"processed": processed, "applied": processed, "created": created, "reused": reused, "failed": failed, "errors": errors, "actor": actor}

    @staticmethod
    def _worker_status(payload: dict[str, str]) -> str:
        status = AccessNowIngestionService._normalize_status(payload.get("accessnow_status", ""))
        return status if status in {"ACTIVE", "DEACTIVATED", "TERMINATED"} else "ACTIVE"

    @staticmethod
    def _apply_engagement(engagement: WorkerEngagementModel, payload: dict[str, str], now: str) -> None:
        for source, target in {"vendor_name": "vendor_name", "job_title": "job_title", "supervisor_name": "supervisor_name", "sponsor_name": "primary_contact_name", "onboarding_date": "onboarding_date", "production_start_date": "production_start_date"}.items():
            if payload.get(source):
                setattr(engagement, target, payload[source])
        engagement.status = AccessNowIngestionService._worker_status(payload)
        engagement.updated_at_utc = now

    @staticmethod
    def _add_identifiers(session, worker_id: str, payload: dict[str, str], now: str) -> None:
        ensure_source_identifiers(session, worker_id, SOURCE_SYSTEM, payload, now)
#endfile
