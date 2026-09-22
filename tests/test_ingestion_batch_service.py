"""Characterization tests for the generic ingestion batch lifecycle."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iam_automation.application.ingestion.batch_service import IngestionBatchService
from iam_automation.application.ingestion.contracts import IngestionRecordInput
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    FactRosterLockAssignmentModel,
    ImportBatchModel,
    IngestionRecordModel,
    QuarantineRecordModel,
    orm_session,
)


class IngestionBatchServiceTests(unittest.TestCase):
    @staticmethod
    def _valid_row(*, row_number: int = 2, source_record_key: str = "TTEC:E100") -> IngestionRecordInput:
        payload = {
            "vendor_name": "TTEC",
            "vendor_employee_id": source_record_key.split(":", 1)[-1],
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
        }
        return IngestionRecordInput(
            row_number=row_number,
            source_record_key=source_record_key,
            normalized_fields=payload,
            source_fields=payload,
        )

    @staticmethod
    def _persist(database: Path, rows: tuple[IngestionRecordInput, ...], *, source_file: str = "roster.xlsx", checksum: str = "checksum"):
        return IngestionBatchService(database).persist_rows(
            source_system="ROSTER_LOCK",
            filename=source_file,
            source_file=source_file,
            source_checksum=checksum,
            source_modified_at_utc="2026-09-22T12:00:00+00:00",
            created_by="test",
            total_rows=len(rows),
            rows=rows,
        )

    def test_lifecycle_persists_records_facts_counts_and_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            invalid = IngestionRecordInput(
                row_number=3,
                source_record_key="TTEC:",
                normalized_fields={"vendor_name": "TTEC", "vendor_employee_id": ""},
                source_fields={"Vendor Name": "TTEC", "Vendor employee ID": ""},
                validation_error="Vendor employee ID is required.",
            )

            outcome = self._persist(database, (self._valid_row(), invalid))

            self.assertEqual(outcome.total_rows, 2)
            self.assertEqual(outcome.staged_rows, 1)
            self.assertEqual(outcome.quarantine_rows, 1)
            self.assertEqual(outcome.duplicate_rows, 0)
            self.assertEqual(outcome.status, "COMPLETED_WITH_WARNINGS")
            with orm_session(database) as session:
                batch = session.get(ImportBatchModel, outcome.batch_id)
                self.assertIsNotNone(batch)
                self.assertEqual((batch.status, batch.valid_rows, batch.quarantine_rows), ("COMPLETED_WITH_WARNINGS", 1, 1))
                record = session.query(IngestionRecordModel).one()
                self.assertEqual(record.status, "STAGED")
                self.assertEqual(record.normalized_json, "")
                self.assertEqual(record.payload_json, "")
                self.assertEqual(session.query(QuarantineRecordModel).count(), 1)
                self.assertEqual(session.query(FactRosterLockAssignmentModel).count(), 1)

    def test_lifecycle_coordinates_existing_payload_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            first = self._persist(database, (self._valid_row(),), source_file="roster-1.xlsx", checksum="checksum-1")
            second = self._persist(database, (self._valid_row(),), source_file="roster-2.xlsx", checksum="checksum-2")

            self.assertEqual(first.staged_rows, 1)
            self.assertEqual(second.staged_rows, 0)
            self.assertEqual(second.duplicate_rows, 1)
            with orm_session(database) as session:
                second_batch = session.get(ImportBatchModel, second.batch_id)
                self.assertEqual((second_batch.status, second_batch.valid_rows, second_batch.quarantine_rows), ("COMPLETED", 0, 0))
                self.assertEqual(session.query(IngestionRecordModel).count(), 1)

    def test_lifecycle_rolls_back_batch_when_fact_persistence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with patch(
                "iam_automation.application.ingestion.batch_service.StarSchemaWriter.write_batch_in_session",
                side_effect=RuntimeError("fact write failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "fact write failed"):
                    self._persist(database, (self._valid_row(),))

            with orm_session(database) as session:
                self.assertEqual(session.query(ImportBatchModel).count(), 0)
                self.assertEqual(session.query(IngestionRecordModel).count(), 0)


if __name__ == "__main__":
    unittest.main()
