"""
File: tests/test_identity_discovery.py
Purpose: Provides automated regression tests for test identity discovery.
Responsibilities: Exposes or coordinates: IdentityDiscoveryTests.
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

from iam_automation.identity_discovery import list_pending_discoveries, list_windows_traceability, mark_discovery, record_identity_discovery, record_windows_traceability


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

    def test_each_discovery_directory_write_is_an_independent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "database" / "snapshots" / "identity_discoveries"
            first = record_identity_discovery(directory, "DOMAIN\\one", "VDI-01", "REQUESTER")
            second = record_identity_discovery(directory, "DOMAIN\\two", "VDI-02", "REQUESTER")
            self.assertNotEqual(first.discovery_id, second.discovery_id)
            self.assertEqual(len(tuple(directory.glob("*.json"))), 2)
            self.assertEqual(len(list_pending_discoveries(directory)), 2)
            mark_discovery(directory, first.discovery_id, "APPROVED", "admin")
            self.assertEqual(len(list_pending_discoveries(directory)), 1)

    def test_windows_traceability_uses_one_shared_file_per_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "database" / "snapshots" / "windows_traceability"
            first = record_windows_traceability(directory, "DOMAIN\\one", "VDI-01")
            second = record_windows_traceability(directory, "DOMAIN\\two", "VDI-02")
            self.assertNotEqual(first.traceability_id, second.traceability_id)
            self.assertEqual(len(tuple(directory.glob("windows_*.json"))), 2)
            self.assertEqual([item.computer for item in list_windows_traceability(directory)], ["VDI-02", "VDI-01"])


if __name__ == "__main__":
    unittest.main()
#endfile
