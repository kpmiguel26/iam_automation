"""
File: tests/test_temporary_super_operator.py
Purpose: Provides automated regression tests for test temporary super operator.
Responsibilities: Exposes or coordinates: TemporarySuperOperatorTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from iam_automation.application.temporary_super_operator_service import TemporarySuperOperatorService
from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import ROLE_APPLICATION_ADMIN, ROLE_REQUESTER, ROLE_SUPER_OPERATOR


class TemporarySuperOperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = initialize_runtime_database(Path(self.tmp.name) / "runtime.sqlite")
        self.users = UserService(self.database)
        self.users.create_user("operator", "Transition operator", "secret", [ROLE_REQUESTER])
        self.service = TemporarySuperOperatorService(self.database, Path(self.tmp.name) / "audit")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def window(days: int = 1):
        start = datetime.now(timezone.utc) - timedelta(minutes=1)
        end = start + timedelta(days=days)
        return start.isoformat(), end.isoformat()

    def test_grant_adds_temporary_role_without_persisting_it_as_a_user_role(self):
        starts, expires = self.window()
        elevation_id = self.service.grant("operator", starts, expires, "Budget transition testing", "master")

        user = self.users.list_users()[0]
        self.assertNotIn(ROLE_SUPER_OPERATOR, user.roles)
        self.assertIn(ROLE_SUPER_OPERATOR, self.service.effective_roles("operator", user.roles))
        self.assertEqual(self.service.list_all()[0].elevation_id, elevation_id)

    def test_revoke_removes_effective_role(self):
        starts, expires = self.window()
        elevation_id = self.service.grant("operator", starts, expires, "Temporary coverage", "master")
        self.service.revoke(elevation_id, "master")

        self.assertNotIn(ROLE_SUPER_OPERATOR, self.service.effective_roles("operator", (ROLE_REQUESTER,)))
        self.assertEqual(self.service.list_all()[0].status, "REVOKED")

    def test_expired_access_is_removed_and_marked(self):
        start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        expires = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.service.grant("operator", start, expires, "Expired test window", "master")

        self.assertNotIn(ROLE_SUPER_OPERATOR, self.service.effective_roles("operator", (ROLE_REQUESTER,)))
        self.assertEqual(self.service.list_all()[0].status, "EXPIRED")

    def test_dates_and_reason_are_required(self):
        starts, expires = self.window()
        with self.assertRaisesRegex(ValueError, "reason"):
            self.service.grant("operator", starts, expires, "", "master")
        with self.assertRaisesRegex(ValueError, "ISO"):
            self.service.grant("operator", "tomorrow", expires, "Test", "master")
        with self.assertRaisesRegex(ValueError, "after"):
            self.service.grant("operator", expires, starts, "Test", "master")


if __name__ == "__main__":
    unittest.main()
