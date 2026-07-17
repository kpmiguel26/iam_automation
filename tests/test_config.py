from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation import config


class ConfigTests(unittest.TestCase):
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
            payload = config.validation_payload(
                {
                    "published_access_db_path": str(db),
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
            payload = config.validation_payload(
                {
                    "published_access_db_path": str(db),
                    "sharepoint_root_path": str(root),
                    "workspace_path": str(workspace),
                    "backup_folder_path": str(backup),
                    "audit_folder_path": str(audit),
                }
            )
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
