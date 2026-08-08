"""
File: tests/test_employee_scale.py
Purpose: Provides automated regression tests for test employee scale.
Responsibilities: Exposes or coordinates: EmployeeScaleTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from iam_automation.application.employee_service import EmployeeService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import WorkerModel, orm_session


class EmployeeScaleTests(unittest.TestCase):
    def test_employee_directory_handles_twelve_thousand_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = "2026-08-07T00:00:00+00:00"
            workers = [
                WorkerModel(
                    worker_id=f"worker-{index:05d}",
                    first_name="Test",
                    last_name=f"Worker {index:05d}",
                    display_name=f"Test Worker {index:05d}",
                    canonical_email=f"worker{index:05d}@example.com",
                    status="ACTIVE",
                    record_version=1,
                    created_at_utc=now,
                    updated_at_utc=now,
                )
                for index in range(12_000)
            ]
            with orm_session(database) as session:
                session.add_all(workers)

            service = EmployeeService(database)
            started = time.perf_counter()
            page, total = service.list_workers_page(page=1, per_page=25)
            statuses, vendors, sources = service.filter_values()
            elapsed = time.perf_counter() - started

            self.assertEqual(total, 12_000)
            self.assertEqual(len(page), 25)
            self.assertEqual(statuses, ["ACTIVE"])
            self.assertEqual(vendors, [])
            self.assertEqual(sources, [])
            # This is intentionally generous for Windows/OneDrive-backed
            # workstations while still catching accidental full-table payload
            # loading in the directory and filter endpoints.
            self.assertLess(elapsed, 8.0, f"employee directory scale check took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
