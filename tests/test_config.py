"""
File: tests/test_config.py
Purpose: Provides automated regression tests for test config.
Responsibilities: Exposes or coordinates: ConfigTests.
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
from unittest.mock import patch

from iam_automation import config


class ConfigTests(unittest.TestCase):
    def test_toml_reader_uses_text_loads_for_python310_fallbacks(self):
        path = Path(tempfile.mktemp(suffix=".toml"))
        path.write_text("[paths]\nsharepoint_root_path = \"C:/OneDrive/IAM\"\n", encoding="utf-8")

        class Parser:
            @staticmethod
            def loads(value):
                self.assertIsInstance(value, str)
                return {"paths": {"sharepoint_root_path": "C:/OneDrive/IAM"}}

            @staticmethod
            def load(_value):
                raise AssertionError("binary load must not be used")

        try:
            with patch.object(config, "tomllib", Parser):
                defaults = config._config_defaults(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(defaults["sharepoint_root_path"], "C:/OneDrive/IAM")

    def test_sample_config_has_no_machine_specific_absolute_paths(self):
        defaults = config._config_defaults(config.DEFAULT_CONFIG_PATH)
        self.assertEqual(defaults["sharepoint_root_path"], "")
        self.assertEqual(defaults["workspace_path"], "")
        self.assertEqual(defaults["backup_folder_path"], "")

    def test_rejects_sharepoint_web_links(self):
        payload = config.validation_payload(
            {
                "published_access_db_path": "https://tenant.sharepoint.com/sites/iam/iam.accdb",
                "sharepoint_root_path": "https://tenant.sharepoint.com/sites/iam",
                "workspace_path": "/tmp/IAMAutomation/workspace",
                "backup_folder_path": "/tmp/backup",
                "audit_folder_path": "/tmp/audit",
            }
        )
        statuses = {item["key"]: item["status"] for item in payload["resources"]}
        self.assertEqual(statuses["published_access_db_path"], "web_path")
        self.assertEqual(statuses["sharepoint_root_path"], "web_path")
        self.assertFalse(payload["ok"])

    def test_rejects_workspace_inside_onedrive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "OneDrive - Kaiser Permanente" / "IAMAutomation"
            workspace = root / "workspace"
            root.mkdir(parents=True)
            workspace.mkdir()
            db = root / "iam.accdb"
            db.write_text("", encoding="utf-8")
            runtime = root / "iam_runtime.sqlite"
            runtime.write_bytes(b"sqlite-placeholder")
            payload = config.validation_payload(
                {
                    "published_access_db_path": str(db),
                    "published_runtime_db_path": str(runtime),
                    "sharepoint_root_path": str(root),
                    "workspace_path": str(workspace),
                    "backup_folder_path": str(root / "backups"),
                    "audit_folder_path": str(root / "audit"),
                }
            )
        statuses = {item["key"]: item["status"] for item in payload["resources"]}
        self.assertEqual(statuses["workspace_path"], "workspace_in_onedrive")
        self.assertFalse(payload["ok"])

    def test_accepts_onedrive_db_and_local_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "OneDrive - Kaiser Permanente" / "IAMAutomation"
            workspace = Path(tmp) / "IAMAutomation" / "workspace"
            backup = root / "backups"
            audit = root / "audit"
            for folder in (root, workspace, backup, audit):
                folder.mkdir(parents=True)
            db = root / "iam.accdb"
            db.write_text("", encoding="utf-8")
            runtime = root / "iam_runtime.sqlite"
            runtime.write_bytes(b"sqlite-placeholder")
            payload = config.validation_payload(
                {
                    "published_access_db_path": str(db),
                    "published_runtime_db_path": str(runtime),
                    "sharepoint_root_path": str(root),
                    "workspace_path": str(workspace),
                    "backup_folder_path": str(backup),
                    "audit_folder_path": str(audit),
                }
            )
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
#endfile
