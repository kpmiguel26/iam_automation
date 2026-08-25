"""
File: tests/test_governance.py
Purpose: Provides automated regression tests for test governance.
Responsibilities: Exposes or coordinates: GovernanceTests.
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

from iam_automation.application.governance_service import GovernanceService
from iam_automation.database.runtime_schema import initialize_runtime_database


class GovernanceTests(unittest.TestCase):
    def test_publish_creates_manifest_and_restore_replaces_published_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = initialize_runtime_database(root / "local.sqlite")
            published = initialize_runtime_database(root / "published.sqlite")
            service = GovernanceService(local_runtime_path=local, published_runtime_path=published, audit_path=root / "audit")
            first = service.publish("master")
            self.assertTrue(first.manifest_path.exists())
            backup = service.list_backups()[0]
            restored = service.restore("master", backup.name)
            self.assertEqual(len(restored.checksum), 64)
            self.assertTrue(service.list_audit_events())

    def test_expected_checksum_blocks_stale_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = initialize_runtime_database(root / "local.sqlite")
            published = initialize_runtime_database(root / "published.sqlite")
            service = GovernanceService(local_runtime_path=local, published_runtime_path=published, audit_path=root / "audit")
            with self.assertRaises(Exception):
                service.publish("master", expected_checksum="stale")


if __name__ == "__main__":
    unittest.main()
#endfile
