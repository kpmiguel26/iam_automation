"""
File: tests/test_worker_history.py
Purpose: Provides automated regression tests for test worker history.
Responsibilities: Exposes or coordinates: WorkerHistoryTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.worker_history_service import backfill_missing_worker_versions, record_worker_version
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import WorkerMergeEventModel, WorkerModel, WorkerProfileVersionModel, orm_session


class WorkerHistoryTests(unittest.TestCase):
    def _worker(self, worker_id: str, first_name: str) -> WorkerModel:
        return WorkerModel(
            worker_id=worker_id,
            first_name=first_name,
            last_name="Worker",
            display_name=f"{first_name} Worker",
            canonical_email=f"{first_name.lower()}@example.com",
            status="ACTIVE",
            record_version=1,
            created_at_utc="2026-07-31T00:00:00+00:00",
            updated_at_utc="2026-07-31T00:00:00+00:00",
        )

    def test_existing_worker_gets_idempotent_baseline_and_changes_append_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            worker_id = str(uuid.uuid4())
            with orm_session(database) as session:
                session.add(self._worker(worker_id, "Ada"))

            self.assertEqual(backfill_missing_worker_versions(database), 1)
            self.assertEqual(backfill_missing_worker_versions(database), 0)
            with orm_session(database) as session:
                worker = session.get(WorkerModel, worker_id)
                worker.first_name = "Grace"
                worker.display_name = "Grace Worker"
                record_worker_version(session, worker_id, actor="admin", change_type="ADMIN_UPDATE", changed_fields=["first_name", "display_name"])

                versions = session.query(WorkerProfileVersionModel).filter_by(worker_id=worker_id).order_by(WorkerProfileVersionModel.version_number).all()
                self.assertEqual([item.version_number for item in versions], [1, 2])
                self.assertIn('"first_name": "Ada"', versions[0].snapshot_json)
                self.assertIn('"first_name": "Grace"', versions[1].snapshot_json)
                self.assertEqual(worker.record_version, 2)

    def test_merge_preserves_duplicate_as_superseded_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            survivor_id, duplicate_id = str(uuid.uuid4()), str(uuid.uuid4())
            with orm_session(database) as session:
                session.add(self._worker(survivor_id, "Ada"))
                session.add(self._worker(duplicate_id, "Ada"))

            result = EmployeeService(database).merge_workers(survivor_id, duplicate_id, "Same person imported from two sources", "admin")
            self.assertEqual(result["survivor_worker_id"], survivor_id)
            with orm_session(database) as session:
                duplicate = session.get(WorkerModel, duplicate_id)
                self.assertEqual(duplicate.status, "DUPLICATE_SUPERSEDED")
                self.assertEqual(duplicate.superseded_by_worker_id, survivor_id)
                self.assertEqual(session.query(WorkerMergeEventModel).count(), 1)
                self.assertEqual(session.query(WorkerProfileVersionModel).filter_by(worker_id=survivor_id).count(), 1)
                self.assertEqual(session.query(WorkerProfileVersionModel).filter_by(worker_id=duplicate_id).count(), 1)

            active, total = EmployeeService(database).list_workers_page(page=1, per_page=25)
            self.assertEqual(total, 1)
            self.assertEqual(active[0].worker_id, survivor_id)


if __name__ == "__main__":
    unittest.main()
#endfile
