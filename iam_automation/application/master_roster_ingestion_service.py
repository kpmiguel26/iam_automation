"""Stage Master Roster workbooks without changing canonical employees."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, QuarantineRecordModel, orm_session
from .ingestion.common import file_modified_at_utc, read_stable_bytes
from .ingestion.dedup import latest_payload_digests, payload_digest, serialize_payload
from .star_schema_writer import StarSchemaWriter
from ..source_adapters.master_roster import (
    HEADER_SCAN_LIMIT,
    REQUIRED_HEADERS,
    header_index,
    json_value,
    normalize_row,
    read_rows,
    unique_headers,
    validation_error,
)


@dataclass(frozen=True)
class MasterRosterIngestionResult:
    batch_id: str
    filename: str
    total_rows: int
    staged_rows: int
    quarantine_rows: int
    source_checksum: str
    already_processed: bool = False


class MasterRosterIngestionService:
    """Read and stage Master Roster observations for read-only review."""

    SOURCE_SYSTEM = "MASTER_ROSTER"
    HEADER_SCAN_LIMIT = HEADER_SCAN_LIMIT
    REQUIRED_HEADERS = REQUIRED_HEADERS

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def ingest_file(self, path: Path, actor: str = "workspace-watcher") -> MasterRosterIngestionResult:
        path = path.expanduser().resolve()
        if path.suffix.lower() != ".xlsx":
            raise ValueError("Master Roster ingestion requires an XLSX workbook.")
        content = read_stable_bytes(path)
        checksum = hashlib.sha256(content).hexdigest()
        with orm_session(self.database_path) as session:
            existing = session.scalar(select(IngestionRecordModel).where(IngestionRecordModel.source_file == str(path), IngestionRecordModel.source_checksum == checksum))
            if existing:
                batch = session.get(ImportBatchModel, existing.batch_id)
                return MasterRosterIngestionResult(existing.batch_id, path.name, batch.total_rows if batch else 0, batch.valid_rows if batch else 0, batch.quarantine_rows if batch else 0, checksum, True)

        rows = self._read_rows(content)
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        staged = 0
        quarantined = 0
        seen_keys: set[str] = set()
        with orm_session(self.database_path) as session:
            session.add(ImportBatchModel(batch_id=batch_id, filename=path.name, source_type=self.SOURCE_SYSTEM, status="PROCESSING", total_rows=len(rows), valid_rows=0, quarantine_rows=0, created_by=actor, created_at_utc=now, source_modified_at_utc=file_modified_at_utc(path)))
            existing_payloads = latest_payload_digests(
                session,
                self.SOURCE_SYSTEM,
                {str(self._normalize({str(key): self._json_value(value) for key, value in raw.items() if key}).get("employee_number") or "").strip() for _, raw in rows},
            )
            for row_number, raw_row in rows:
                payload = {str(key): self._json_value(value) for key, value in raw_row.items() if key}
                normalized = self._normalize(payload)
                source_key = str(normalized.get("employee_number") or "").strip()
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
        return MasterRosterIngestionResult(batch_id, path.name, len(rows), staged, quarantined, checksum)

    @classmethod
    def _read_rows(cls, content: bytes) -> list[tuple[int, dict[str, object]]]:
        return read_rows(content)

    @classmethod
    def _header_index(cls, values: list[tuple[object, ...]]) -> int:
        return header_index(values)

    @staticmethod
    def _unique_headers(row: tuple[object, ...]) -> list[str]:
        return unique_headers(row)

    @classmethod
    def _normalize(cls, payload: dict[str, object]) -> dict[str, object]:
        return normalize_row(payload)

    @staticmethod
    def _validation_error(normalized: dict[str, object], source_key: str, seen_keys: set[str]) -> str | None:
        return validation_error(normalized, source_key, seen_keys)

    @staticmethod
    def _json_value(value: object) -> object:
        return json_value(value)
