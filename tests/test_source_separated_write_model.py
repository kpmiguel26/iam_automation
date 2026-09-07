from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.accessnow_ingestion_service import AccessNowIngestionService
from iam_automation.database import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import IngestionRecordModel, orm_session


class SourceSeparatedWriteModelTests(unittest.TestCase):
    def test_accessnow_ingestion_writes_typed_fact_employee_bridge_history_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            folder = root / "accessnow"
            folder.mkdir()
            with (folder / "active.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["Employee ID", "NUID", "First Name", "Last Name", "KP Email", "Employee Status"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Employee ID": "A-100",
                        "NUID": "N-100",
                        "First Name": "Ada",
                        "Last Name": "Lovelace",
                        "KP Email": "ada@example.com",
                        "Employee Status": "ACTIVE",
                    }
                )

            result = AccessNowIngestionService(database).ingest_folder(folder)
            with orm_session(database) as session:
                record_id = session.query(IngestionRecordModel.record_id).filter_by(source_system="ACCESSNOW").one()[0]
            applied = AccessNowIngestionService(database).apply_approved_records([record_id], "test")

            self.assertEqual(applied["processed"], 1)
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM fact_accessnow_employee WHERE batch_id = ?", (result.batch_id,)).fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dim_employee").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM bridge_employee_identifier").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT status_code FROM fact_employee_status_event").fetchone()[0], "ACTIVE")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM fact_employee_field_history").fetchone()[0], 4)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
