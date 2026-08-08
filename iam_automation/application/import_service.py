"""
File: iam_automation/application/import_service.py
Purpose: Implements the application service for import service workflows.
Responsibilities: Exposes or coordinates: ImportBatch, ImportService.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import ImportBatchModel, QuarantineRecordModel, orm_session


@dataclass(frozen=True)
class ImportBatch:
    batch_id: str
    filename: str
    source_type: str
    status: str
    total_rows: int
    valid_rows: int
    quarantine_rows: int
    created_by: str
    created_at_utc: str


class ImportService:
    """Stages Excel/CSV input and quarantines invalid rows before business writes."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def import_bytes(self, filename: str, content: bytes, actor: str) -> ImportBatch:
        name = Path(filename or "upload").name
        suffix = Path(name).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("Only CSV and XLSX imports are supported.")
        rows = self._read_rows(suffix, content)
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        quarantine = []
        valid = 0
        for row_number, row in enumerate(rows, start=2):
            cleaned = {str(key).strip().lower(): str(value or "").strip() for key, value in row.items() if key}
            if not cleaned.get("employee_id"):
                quarantine.append((row_number, "Required column employee_id is missing.", cleaned))
            else:
                valid += 1
        status = "COMPLETED" if not quarantine else "COMPLETED_WITH_WARNINGS"
        with orm_session(self.database_path) as session:
            session.add(ImportBatchModel(batch_id=batch_id, filename=name, source_type=suffix[1:].upper(), status=status, total_rows=len(rows), valid_rows=valid, quarantine_rows=len(quarantine), created_by=actor, created_at_utc=now, completed_at_utc=now))
            for row_number, reason, payload in quarantine:
                session.add(QuarantineRecordModel(quarantine_id=str(uuid.uuid4()), batch_id=batch_id, row_number=row_number, reason=reason, payload_json=json.dumps(payload, sort_keys=True), status="OPEN", created_at_utc=now))
        return ImportBatch(batch_id, name, suffix[1:].upper(), status, len(rows), valid, len(quarantine), actor, now)

    def list_batches(self) -> list[ImportBatch]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(ImportBatchModel).order_by(ImportBatchModel.created_at_utc.desc())).all()
            return [self._to_batch(row) for row in rows]

    def list_quarantine(self, *, open_only: bool = False) -> list[dict]:
        statement = select(QuarantineRecordModel).order_by(QuarantineRecordModel.created_at_utc.desc())
        if open_only:
            statement = statement.where(QuarantineRecordModel.status == "OPEN")
        with orm_session(self.database_path) as session:
            return [{"quarantine_id": row.quarantine_id, "batch_id": row.batch_id, "row_number": row.row_number, "reason": row.reason, "payload": json.loads(row.payload_json), "status": row.status, "created_at_utc": row.created_at_utc} for row in session.scalars(statement).all()]

    def resolve_quarantine(self, quarantine_id: str, actor: str) -> None:
        with orm_session(self.database_path) as session:
            row = session.get(QuarantineRecordModel, quarantine_id)
            if row is None:
                raise ValueError("Quarantine record was not found.")
            if row.status != "OPEN":
                raise ValueError("Quarantine record is already resolved.")
            row.status = "RESOLVED"
            row.resolved_by = actor
            row.resolved_at_utc = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_rows(suffix: str, content: bytes) -> list[dict[str, str]]:
        if suffix == ".csv":
            return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        try:
            from openpyxl import load_workbook
        except ModuleNotFoundError as exc:
            raise RuntimeError("XLSX imports require openpyxl.") from exc
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Data Validation extension is not supported and will be removed",
                category=UserWarning,
            )
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheet = workbook.active
            values = list(sheet.values)
            if not values:
                return []
            headers = [str(value or "").strip() for value in values[0]]
            return [dict(zip(headers, row)) for row in values[1:]]
        finally:
            workbook.close()

    @staticmethod
    def _to_batch(row: ImportBatchModel) -> ImportBatch:
        return ImportBatch(row.batch_id, row.filename, row.source_type, row.status, row.total_rows, row.valid_rows, row.quarantine_rows, row.created_by, row.created_at_utc)
