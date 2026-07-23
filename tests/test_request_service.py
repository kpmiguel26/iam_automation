from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.application.request_service import RequestService
from iam_automation.application.publication_service import PublicationService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_REQUESTER, ROLE_REVIEWER


class RequestServiceTests(unittest.TestCase):
    def test_request_can_be_created_assigned_and_decided(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = RequestService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            requester = CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer", "VDI-02", (ROLE_REVIEWER,))
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

    def test_approval_enqueues_publication_and_delegation_reassigns_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RequestService(database)
            requester = CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer", "VDI-02", (ROLE_REVIEWER,))
            item = service.create(requester, "CREATE_EMPLOYEE", "W-102", {"first_name": "Luis"}, "Onboarding")
            self.assertEqual(service.reassign_for_delegation("reviewer", "backup.reviewer", "admin", "Absence coverage"), 1)
            queued = service.list_requests(queue=True)[0]
            self.assertEqual(queued.assigned_to, "backup.reviewer")
            service.decide(item.request_id, reviewer, "APPROVED", "Validated")
            self.assertEqual(PublicationService(database).list_pending()[0].request_id, item.request_id)


if __name__ == "__main__":
    unittest.main()
