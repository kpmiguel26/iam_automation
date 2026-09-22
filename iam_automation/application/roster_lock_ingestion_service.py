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
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, orm_session
from .ingestion.batch_service import IngestionBatchService
from .ingestion.contracts import IngestionRecordInput
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
        record_inputs: list[IngestionRecordInput] = []
        for row_number, raw_row in enumerate(rows, start=2):
            payload = {str(key).strip(): self._json_value(value) for key, value in raw_row.items() if key is not None and str(key).strip()}
            normalized = self._normalize(payload)
            source_key = f"{normalized.get('vendor_name', '')}:{normalized.get('vendor_employee_id', '')}"
            record_inputs.append(
                IngestionRecordInput(
                    row_number=row_number,
                    source_record_key=source_key,
                    normalized_fields=normalized,
                    source_fields=payload,
                )
            )

        outcome = IngestionBatchService(self.database_path).persist_rows(
            source_system=self.SOURCE_SYSTEM,
            filename=path.name,
            source_file=str(path),
            source_checksum=checksum,
            source_modified_at_utc=file_modified_at_utc(path),
            created_by="workspace-watcher",
            total_rows=len(rows),
            rows=record_inputs,
            validate_row=lambda row, seen_keys: self._validation_error(
                dict(row.normalized_fields), row.source_record_key, seen_keys
            ),
        )
        return RosterLockIngestionResult(
            outcome.batch_id,
            path.name,
            outcome.total_rows,
            outcome.staged_rows,
            outcome.quarantine_rows,
        )

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
