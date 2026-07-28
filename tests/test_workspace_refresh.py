from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.request_service import RequestService
from iam_automation.application.workspace_refresh_service import WorkspaceRefreshService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_REQUESTER
from iam_automation.runtime_sync import sync_runtime_snapshot


class WorkspaceRefreshTests(unittest.TestCase):
    def test_refresh_preserves_local_pending_request_as_shared_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            initialize_runtime_database(published)
            local = root / "runtime.sqlite"
            sync_runtime_snapshot(published, local)
            request = RequestService(local).create(CurrentUser("requester", "VDI-01", (ROLE_REQUESTER,)), "CREATE_EMPLOYEE", "E100", {"first_name": "Test"}, "Refresh test")
            connection = sqlite3.connect(published)
            try:
                connection.execute("UPDATE app_metadata SET updated_at_utc = datetime('now') WHERE metadata_key = 'schema_version'")
                connection.commit()
            finally:
                connection.close()
            service = WorkspaceRefreshService(local, published, root)
            version, exported = service.refresh("requester")
            self.assertTrue(version.published_checksum)
            self.assertEqual(exported, 1)
            self.assertFalse(version.update_available)
            self.assertEqual(len(tuple((root / "requests" / "pending").glob(f"*_{request.request_id}.json"))), 1)
            self.assertFalse(RequestService(local).list_requests(creator="requester"))


if __name__ == "__main__":
    unittest.main()
