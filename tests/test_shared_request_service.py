from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.application.shared_request_service import SharedRequestService
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_SUPER_OPERATOR


class SharedRequestServiceTests(unittest.TestCase):
    def test_request_lifecycle_is_json_only_until_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sharepoint"
            service = SharedRequestService(root)
            requester = CurrentUser("requester.test", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer.test", "VDI-02", (ROLE_APPLICATION_ADMIN,))
            request = service.create(requester, "CREATE_EMPLOYEE", "E-100", {"first_name": "Ana"}, "Onboarding")
            self.assertEqual(len(tuple((root / "requests" / "pending").glob("*.json"))), 1)
            with self.assertRaises(PermissionError):
                service.decide(request.request_id, requester, "APPROVED", "Cannot self approve")
            service.assign(request.request_id, reviewer.username, "admin", "Coverage")
            item, self_approval = service.decide(request.request_id, reviewer, "APPROVED", "Validated")
            self.assertFalse(self_approval)
            self.assertEqual(item.status, "APPROVED")
            self.assertEqual(len(tuple((root / "requests" / "approved").glob("*.json"))), 1)
            self.assertFalse((root / "runtime.sqlite").exists())

    def test_super_operator_can_self_approve_with_auditable_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sharepoint"
            service = SharedRequestService(root)
            operator = CurrentUser("operator", "VDI-01", (ROLE_REQUESTER, ROLE_SUPER_OPERATOR))
            request = service.create(operator, "UPDATE_EMPLOYEE", "E-101", {"lob": "IT"}, "Temporary test")
            item, self_approval = service.decide(request.request_id, operator, "APPROVED", "Break-glass test approval")
            self.assertTrue(self_approval)
            self.assertEqual(item.status, "APPROVED")

    def test_rejection_requires_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sharepoint"
            service = SharedRequestService(root)
            requester = CurrentUser("requester.test", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer.test", "VDI-02", (ROLE_APPLICATION_ADMIN,))
            request = service.create(requester, "UPDATE_EMPLOYEE", "E-102", {"vendor_name": "TTEC"}, "Vendor correction")
            service.assign(request.request_id, reviewer.username, "admin", "Coverage")
            with self.assertRaisesRegex(ValueError, "rejection reason"):
                service.decide(request.request_id, reviewer, "REJECTED", "")
            item, self_approval = service.decide(request.request_id, reviewer, "REJECTED", "Source does not support this change")
            self.assertFalse(self_approval)
            self.assertEqual(item.review_note, "Source does not support this change")

    def test_roster_lock_import_is_a_shared_request_for_reviewer_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sharepoint"
            service = SharedRequestService(root)
            requester = CurrentUser("admin", "VDI-01", (ROLE_REQUESTER,))
            reviewer = CurrentUser("reviewer", "VDI-02", (ROLE_APPLICATION_ADMIN,))
            request = service.create(
                requester,
                "IMPORT_ROSTER_LOCK",
                "batch-001",
                {"batch_ids": ["batch-001"], "record_ids": ["record-001"], "record_count": 1},
                "Review roster lock import",
            )
            service.assign(request.request_id, reviewer.username, "admin", "Import review")
            item, self_approval = service.decide(request.request_id, reviewer, "APPROVED", "Validated source workbook")
            self.assertFalse(self_approval)
            self.assertEqual(item.operation_type, "IMPORT_ROSTER_LOCK")
            self.assertEqual(item.entity_type, "ImportBatch")
            self.assertEqual(item.status, "APPROVED")


if __name__ == "__main__":
    unittest.main()
