"""
File: iam_automation/application/roster_lock_ingestion_service.py
Purpose: Implements the application service for roster lock ingestion service workflows.
Responsibilities: Exposes or coordinates: RosterLockIngestionResult, RosterLockIngestionService.
Dependencies: sqlalchemy, infrastructure, stable_file_read
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, QuarantineRecordModel, orm_session
from .ingestion.dedup import latest_payload_digests, payload_digest, serialize_payload
from ..infrastructure.sqlite.star_schema_writer import StarSchemaWriter
from .ingestion.common import file_modified_at_utc, read_stable_bytes
from ..source_adapters.roster_lock import json_value, normalize_row, read_rows, validation_error


@dataclass(frozen=True)
class RosterLockIngestionResult:
    batch_id: str
    filename: str
    total_rows: int
    staged_rows: int
    quarantine_rows: int
    already_processed: bool = False


class RosterLockIngestionService:
    """Stage vendor Roster Lock workbooks without creating canonical workers."""

    SOURCE_SYSTEM = "ROSTER_LOCK"

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def ingest_file(self, path: Path) -> RosterLockIngestionResult:
        path = path.expanduser().resolve()
        if path.suffix.lower() != ".xlsx":
            raise ValueError("Roster Lock ingestion requires an XLSX workbook.")
        content = read_stable_bytes(path)
        checksum = hashlib.sha256(content).hexdigest()
        with orm_session(self.database_path) as session:
            existing = session.scalar(select(IngestionRecordModel).where(IngestionRecordModel.source_file == str(path), IngestionRecordModel.source_checksum == checksum))
            if existing:
                batch = session.get(ImportBatchModel, existing.batch_id)
                return RosterLockIngestionResult(existing.batch_id, path.name, batch.total_rows if batch else 0, batch.valid_rows if batch else 0, batch.quarantine_rows if batch else 0, True)

        rows = self._read_rows(content)
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        staged = 0
        quarantined = 0
        seen_keys: set[str] = set()
        with orm_session(self.database_path) as session:
            session.add(ImportBatchModel(batch_id=batch_id, filename=path.name, source_type="ROSTER_LOCK", status="PROCESSING", total_rows=len(rows), valid_rows=0, quarantine_rows=0, created_by="workspace-watcher", created_at_utc=now, source_modified_at_utc=file_modified_at_utc(path)))
            existing_payloads = latest_payload_digests(
                session,
                self.SOURCE_SYSTEM,
                {f"{self._normalize({str(key).strip(): self._json_value(value) for key, value in raw.items() if key is not None and str(key).strip()}).get('vendor_name', '')}:{self._normalize({str(key).strip(): self._json_value(value) for key, value in raw.items() if key is not None and str(key).strip()}).get('vendor_employee_id', '')}" for raw in rows},
            )
            for row_number, raw_row in enumerate(rows, start=2):
                payload = {str(key).strip(): self._json_value(value) for key, value in raw_row.items() if key is not None and str(key).strip()}
                normalized = self._normalize(payload)
                source_key = f"{normalized.get('vendor_name', '')}:{normalized.get('vendor_employee_id', '')}"
                normalized_json = serialize_payload(normalized)
                reason = self._validation_error(normalized, source_key, seen_keys)
                if reason:
                    quarantined += 1
                    session.add(QuarantineRecordModel(quarantine_id=str(uuid.uuid4()), batch_id=batch_id, row_number=row_number, reason=reason, payload_json=json.dumps(payload, sort_keys=True), status="OPEN", created_at_utc=now))
                    continue
                if existing_payloads.get(source_key) == payload_digest(normalized_json):
                    continue
                seen_keys.add(source_key)
                staged += 1
                session.add(IngestionRecordModel(record_id=str(uuid.uuid4()), batch_id=batch_id, source_system=self.SOURCE_SYSTEM, source_file=str(path), source_checksum=checksum, row_number=row_number, source_record_key=source_key, normalized_json=normalized_json, payload_json=json.dumps(payload, sort_keys=True), status="STAGED", created_at_utc=now))
            StarSchemaWriter.write_batch_in_session(session, batch_id, now)
            batch = session.get(ImportBatchModel, batch_id)
            batch.valid_rows = staged
            batch.quarantine_rows = quarantined
            batch.status = "COMPLETED" if quarantined == 0 else "COMPLETED_WITH_WARNINGS"
            batch.completed_at_utc = datetime.now(timezone.utc).isoformat()
        StarSchemaWriter.clear_legacy_payloads(self.database_path, batch_id)
        return RosterLockIngestionResult(batch_id, path.name, len(rows), staged, quarantined)

    @staticmethod
    def _read_rows(content: bytes) -> list[dict[str, object]]:
        return read_rows(content)

    @classmethod
    def _normalize(cls, payload: dict[str, object]) -> dict[str, object]:
        return normalize_row(payload)

    @staticmethod
    def _validation_error(normalized: dict[str, object], source_key: str, seen_keys: set[str]) -> str | None:
        return validation_error(normalized, source_key, seen_keys)

    @staticmethod
    def _json_value(value: object) -> object:
        return json_value(value)
#endfile
