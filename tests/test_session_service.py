from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from iam_automation.application.session_service import SessionService
from iam_automation.database.runtime_schema import initialize_runtime_database


class SessionServiceTests(unittest.TestCase):
    def test_revocation_invalidates_sessions_started_before_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = SessionService(initialize_runtime_database(Path(tmp) / "runtime.sqlite"))
            started = datetime.now(timezone.utc).isoformat()
            service.revoke_user("app.user", "master", "Security review")
            self.assertTrue(service.is_revoked("app.user", started))
            self.assertFalse(service.is_revoked("other.user", started))


if __name__ == "__main__":
    unittest.main()
