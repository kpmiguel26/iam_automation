"""
File: tests/test_workspace_refresh.py
Purpose: Provides automated regression tests for test workspace refresh.
Responsibilities: Exposes or coordinates: WorkspaceRefreshTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
import json
from pathlib import Path

from iam_automation.application.request_service import RequestService
from iam_automation.application.workspace_refresh_service import WorkspaceRefreshService, record_published_source_checksum
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_REQUESTER
from iam_automation.runtime_sync import runtime_manifest_path, sha256_file, sync_runtime_snapshot


class WorkspaceRefreshTests(unittest.TestCase):
    def test_version_detects_local_runtime_changes_after_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            initialize_runtime_database(published)
            local = root / "runtime.sqlite"
            snapshot = sync_runtime_snapshot(published, local)
            record_published_source_checksum(local, snapshot.checksum)
            service = WorkspaceRefreshService(local, published, root)
            self.assertFalse(service.version().update_available)
            connection = sqlite3.connect(local)
            try:
                connection.execute("INSERT INTO app_metadata (metadata_key, metadata_value, updated_at_utc) VALUES ('local_edit', 'yes', datetime('now'))")
                connection.commit()
            finally:
                connection.close()
            version = service.version()
            self.assertTrue(version.local_dirty)
            self.assertTrue(version.update_available)

    def test_version_uses_published_manifest_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            initialize_runtime_database(published)
            local = root / "runtime.sqlite"
            snapshot = sync_runtime_snapshot(published, local)
            record_published_source_checksum(local, snapshot.checksum)

            version = WorkspaceRefreshService(local, published, root).version()

            self.assertEqual(version.published_checksum, snapshot.checksum)
            self.assertFalse(version.update_available)

    def test_version_does_not_wait_when_workspace_lock_is_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            initialize_runtime_database(published)
            local = root / "runtime.sqlite"
            snapshot = sync_runtime_snapshot(published, local)
            record_published_source_checksum(local, snapshot.checksum)
            service = WorkspaceRefreshService(local, published, root)

            from iam_automation.application.workspace_refresh_service import WORKSPACE_IO_LOCK
            ready = threading.Event()
            release = threading.Event()

            def hold_workspace_lock():
                WORKSPACE_IO_LOCK.acquire()
                ready.set()
                release.wait(2)
                WORKSPACE_IO_LOCK.release()

            holder = threading.Thread(target=hold_workspace_lock)
            holder.start()
            self.assertTrue(ready.wait(1))
            version = service.version()
            release.set()
            holder.join(1)

            self.assertEqual(version.published_checksum, snapshot.checksum)

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
                connection.execute("UPDATE app_metadata SET metadata_value = '1.0.1' WHERE metadata_key = 'schema_version'")
                connection.commit()
            finally:
                connection.close()
            manifest_path = runtime_manifest_path(published)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sha256"] = sha256_file(published)
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            service = WorkspaceRefreshService(local, published, root)
            version, exported = service.refresh("requester")
            self.assertTrue(version.published_checksum)
            self.assertEqual(exported, 1)
            self.assertFalse(version.update_available)
            self.assertEqual(len(tuple((root / "requests" / "pending").glob(f"*_{request.request_id}.json"))), 1)
            self.assertFalse(RequestService(local).list_requests(creator="requester"))


if __name__ == "__main__":
    unittest.main()
