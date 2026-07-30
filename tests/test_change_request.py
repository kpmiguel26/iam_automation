from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from iam_automation.change_request import (
    RequestValidationError,
    import_pending_requests,
    load_request_file,
    new_request,
    submit_request,
)
from iam_automation.identity import CurrentUser, ROLE_AUDITOR, ROLE_REQUESTER


class ChangeRequestTests(unittest.TestCase):
    def test_requester_can_create_and_submit_immutable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = CurrentUser("DOMAIN\\requester", "PC01", (ROLE_REQUESTER,))
            request = new_request(
                user=user,
                application_version="0.1.0",
                operation_type="UPDATE_EMPLOYEE",
                entity_type="Employee",
                entity_id="E12345",
                expected_record_version=4,
                payload={"manager_id": "M100"},
                reason="Manager reassignment",
            )
            path = submit_request(request, Path(tmp) / "pending")
            loaded = load_request_file(path)
            self.assertEqual(loaded.request_id, request.request_id)
            self.assertEqual(loaded.status, "PENDING")

    def test_large_import_request_with_portable_previews_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = CurrentUser("DOMAIN\\requester", "PC01", (ROLE_REQUESTER,))
            previews = [{"record_id": str(index), "worker_name": "Worker " + str(index), "source_file": "fieldglass.xlsx", "match_status": "UNMATCHED", "statement_of_work": "TTEC Contact Center Agent Services SOW 11109 " + ("details " * 35)} for index in range(615)]
            request = new_request(
                user=user,
                application_version="0.1.0",
                operation_type="IMPORT_RSR_SUPPLIER_DETAILS",
                entity_type="ImportBatch",
                entity_id="batch-615",
                expected_record_version=0,
                payload={"record_ids": [str(index) for index in range(615)], "record_count": 615, "record_previews": previews},
                reason="Review Fieldglass worker details",
            )
            path = submit_request(request, Path(tmp) / "pending")
            self.assertGreater(path.stat().st_size, 256 * 1024)
            self.assertEqual(load_request_file(path).request_id, request.request_id)

    def test_auditor_cannot_submit_request(self):
        user = CurrentUser("DOMAIN\\auditor", "PC01", (ROLE_AUDITOR,))
        with self.assertRaises(PermissionError):
            new_request(
                user=user,
                application_version="0.1.0",
                operation_type="UPDATE_EMPLOYEE",
                entity_type="Employee",
                entity_id="E12345",
                expected_record_version=4,
                payload={"manager_id": "M100"},
                reason="Manager reassignment",
            )

    def test_malformed_request_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = root / "pending"
            pending.mkdir()
            bad = pending / "20260717T153500Z_9fb2e618-03fe-4ac2-8aa8-2ab864ade902.json"
            bad.write_text("{not json", encoding="utf-8")

            summary = import_pending_requests(
                pending_folder=pending,
                imported_folder=root / "imported",
                quarantine_folder=root / "quarantine",
                processed_registry_path=root / "processed_requests.jsonl",
                batch_id="batch-1",
            )

            self.assertEqual(len(summary["quarantined"]), 1)
            self.assertFalse(bad.exists())

    def test_duplicate_request_id_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = root / "pending"
            user = CurrentUser("DOMAIN\\requester", "PC01", (ROLE_REQUESTER,))
            request = new_request(
                user=user,
                application_version="0.1.0",
                operation_type="UPDATE_EMPLOYEE",
                entity_type="Employee",
                entity_id="E12345",
                expected_record_version=4,
                payload={"manager_id": "M100"},
                reason="Manager reassignment",
            )
            first = submit_request(request, pending)
            duplicate = pending / first.name.replace(".json", "-duplicate.json")
            duplicate = pending / f"20260717T153501Z_{request.request_id}.json"
            duplicate.write_text(json.dumps(asdict(request)), encoding="utf-8")

            summary = import_pending_requests(
                pending_folder=pending,
                imported_folder=root / "imported",
                quarantine_folder=root / "quarantine",
                processed_registry_path=root / "processed_requests.jsonl",
                batch_id="batch-1",
            )
            self.assertEqual(len(summary["imported"]), 1)
            self.assertEqual(len(summary["duplicates"]), 1)


if __name__ == "__main__":
    unittest.main()
