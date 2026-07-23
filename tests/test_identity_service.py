from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.application.identity_service import IdentityService
from iam_automation.database.runtime_schema import initialize_runtime_database


class IdentityServiceTests(unittest.TestCase):
    def test_create_and_update_windows_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = IdentityService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            service.save_identity("DOMAIN\\migue", "Miguel", ["APPLICATION_ADMIN"], True, can_assign_master=False)
            self.assertEqual(service.list_identities()[0].roles, ("APPLICATION_ADMIN",))
            service.save_identity("DOMAIN\\migue", "Miguel A", ["AUDITOR"], False, can_assign_master=False)
            identity = service.list_identities()[0]
            self.assertEqual(identity.display_name, "Miguel A")
            self.assertFalse(identity.active)
            self.assertEqual(identity.roles, ("AUDITOR",))

    def test_application_admin_cannot_assign_master_identity_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = IdentityService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            with self.assertRaises(PermissionError):
                service.save_identity("DOMAIN\\other", "Other", ["MASTER_ADMIN"], True, can_assign_master=False)


if __name__ == "__main__":
    unittest.main()
