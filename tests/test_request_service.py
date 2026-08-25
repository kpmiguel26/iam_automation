"""
File: tests/test_request_service.py
Purpose: Provides automated regression tests for test request service.
Responsibilities: Exposes or coordinates: RequestServiceTests.
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
from pathlib import Path

from iam_automation.application.request_service import RequestService
from iam_automation.application.publication_service import PublicationService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_WRITER


class RequestServiceTests(unittest.TestCase):
    def test_request_can_be_created_assigned_and_decided(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = RequestService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            requester = CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer", "VDI-02", (ROLE_APPLICATION_ADMIN,))
            item = service.create(requester, "CREATE_EMPLOYEE", "W-100", {"first_name": "Ana"}, "New onboarding")
            self.assertEqual(item.status, "PENDING")
            service.assign(item.request_id, reviewer.username, "admin", "Reviewer coverage")
            decided = service.decide(item.request_id, reviewer, "APPROVED", "Validated against roster lock")
            self.assertEqual(decided.status, "APPROVED")
            self.assertEqual(decided.reviewed_by, "reviewer")

    def test_requester_cannot_decide_own_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = RequestService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            requester = CurrentUser("requester", "VDI-01", (ROLE_REVIEWER,))
            item = service.create(requester, "UPDATE_EMPLOYEE", "W-101", {"lob": "IT"}, "Update assignment")
            with self.assertRaises(PermissionError):
                service.decide(item.request_id, requester, "APPROVED", "Self approval")

    def test_only_administrator_can_decide_another_users_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = RequestService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            requester = CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,))
            writer = CurrentUser("writer", "VDI-02", (ROLE_WRITER,))
            item = service.create(requester, "UPDATE_EMPLOYEE", "W-104", {"lob": "IT"}, "Update assignment")
            with self.assertRaises(PermissionError):
                service.decide(item.request_id, writer, "APPROVED", "Validated")
            decided = service.decide(item.request_id, CurrentUser("admin", "VDI-03", (ROLE_APPLICATION_ADMIN,)), "APPROVED", "Validated")
            self.assertEqual(decided.status, "APPROVED")
            self.assertEqual(decided.reviewed_by, "admin")

    def test_pending_request_is_exported_to_sharepoint_connector_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            service = RequestService(database)
            service.create(CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,)), "CREATE_EMPLOYEE", "W-103", {"first_name": "Mia"}, "Onboarding")
            exported = service.export_pending_for_user("requester", root / "sharepoint" / "requests" / "pending")
            files = tuple((root / "sharepoint" / "requests" / "pending").glob("*.json"))
            self.assertEqual(exported, 1)
            self.assertEqual(len(files), 1)

    def test_approval_enqueues_publication_and_delegation_reassigns_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RequestService(database)
            requester = CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer", "VDI-02", (ROLE_APPLICATION_ADMIN,))
            item = service.create(requester, "CREATE_EMPLOYEE", "W-102", {"first_name": "Luis"}, "Onboarding")
            self.assertEqual(service.reassign_for_delegation("reviewer", "backup.reviewer", "admin", "Absence coverage"), 1)
            queued = service.list_requests(queue=True)[0]
            self.assertEqual(queued.assigned_to, "backup.reviewer")
            service.decide(item.request_id, reviewer, "APPROVED", "Validated")
            self.assertEqual(PublicationService(database).list_pending()[0].request_id, item.request_id)


if __name__ == "__main__":
    unittest.main()
#endfile
