"""Stage Master Roster workbooks without changing canonical employees."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, QuarantineRecordModel, orm_session
from .ingestion_dedup import latest_payload_digests, payload_digest, serialize_payload
from .stable_file_read import file_modified_at_utc, read_stable_bytes
from .star_schema_writer import StarSchemaWriter


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
    HEADER_SCAN_LIMIT = 12
    REQUIRED_HEADERS = {"employee number", "employee name"}

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
        try:
            from openpyxl import load_workbook
        except ModuleNotFoundError as exc:
            raise RuntimeError("Master Roster ingestion requires openpyxl.") from exc
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Data Validation extension is not supported and will be removed", category=UserWarning)
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            values = list(workbook.active.values)
            header_index = cls._header_index(values)
            headers = cls._unique_headers(values[header_index])
            return [
                (row_number, dict(zip(headers, row)))
                for row_number, row in enumerate(values[header_index + 1:], start=header_index + 2)
                if any(value not in (None, "") for value in row)
            ]
        finally:
            workbook.close()

    @classmethod
    def _header_index(cls, values: list[tuple[object, ...]]) -> int:
        for index, row in enumerate(values[: cls.HEADER_SCAN_LIMIT]):
            normalized = {str(value or "").strip().casefold() for value in row}
            if cls.REQUIRED_HEADERS.issubset(normalized):
                return index
        raise ValueError("Master Roster workbook must contain Employee Number and Employee Name headers.")

    @staticmethod
    def _unique_headers(row: tuple[object, ...]) -> list[str]:
        counts: dict[str, int] = {}
        headers: list[str] = []
        for index, value in enumerate(row, start=1):
            base = str(value or "").strip() or f"Source Column {index}"
            counts[base] = counts.get(base, 0) + 1
            headers.append(base if counts[base] == 1 else f"{base} [{counts[base]}]")
        return headers

    @classmethod
    def _normalize(cls, payload: dict[str, object]) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for key, value in payload.items():
            canonical = "_".join("".join(character.lower() if character.isalnum() else " " for character in key).split())
            normalized[canonical] = value
        aliases = {
            "source_column_1": "source_row_number",
            "user_principal_name": "email",
            "logonid": "nuid_login_id",
            "logonid_2": "npn_login_id",
        }
        for source, target in aliases.items():
            if source in normalized and target not in normalized:
                normalized[target] = normalized[source]
        employee_name = str(normalized.get("employee_name") or "").strip()
        if employee_name and not normalized.get("first_name"):
            parts = employee_name.split()
            normalized["first_name"] = parts[0]
            normalized["last_name"] = " ".join(parts[1:])
        return normalized

    @staticmethod
    def _validation_error(normalized: dict[str, object], source_key: str, seen_keys: set[str]) -> str | None:
        if not source_key:
            return "Required field Employee Number is missing."
        if not str(normalized.get("employee_name") or "").strip():
            return "Required field Employee Name is missing."
        if source_key in seen_keys:
            return f"Duplicate Master Roster Employee Number detected: {source_key}."
        return None

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value
