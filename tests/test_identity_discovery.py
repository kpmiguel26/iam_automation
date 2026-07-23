from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.identity_discovery import list_pending_discoveries, mark_discovery, record_identity_discovery


class IdentityDiscoveryTests(unittest.TestCase):
    def test_discovery_is_deduplicated_and_can_be_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "database" / "snapshots" / "iam_identity_discovery.json"
            first = record_identity_discovery(path, "DOMAIN\\migue", "VDI-01", "REQUESTER")
            second = record_identity_discovery(path, "domain\\MIGUE", "VDI-01", "REQUESTER")
            self.assertEqual(first.discovery_id, second.discovery_id)
            self.assertEqual(len(list_pending_discoveries(path)), 1)
            mark_discovery(path, first.discovery_id, "APPROVED", "admin")
            self.assertEqual(list_pending_discoveries(path), [])


if __name__ == "__main__":
    unittest.main()
