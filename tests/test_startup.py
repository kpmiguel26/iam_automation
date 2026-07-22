from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from iam_automation.sharepoint_discovery import discover_candidates
from iam_automation.startup import StartupController, StartupState


def make_sharepoint_root(base: Path, name: str = "OneDrive - Test/IAMAutomation") -> Path:
    root = base / name
    for folder in ("requests", "audit", "backups"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "database").mkdir(parents=True, exist_ok=True)
    (root / "database" / "iam_automation.accdb").write_bytes(b"access-placeholder")
    (root / "database" / "snapshots").mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "database" / "snapshots" / "iam_runtime.sqlite")
    connection.execute("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT)")
    connection.commit()
    connection.close()
    return root


class StartupTests(unittest.TestCase):
    def test_discovers_single_onedrive_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_sharepoint_root(Path(tmp))
            candidates = discover_candidates((Path(tmp) / "OneDrive - Test",))
            self.assertEqual([item.path for item in candidates], [root])
            self.assertTrue(candidates[0].is_usable)

    def test_multiple_candidates_are_reported_before_manual_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_sharepoint_root(base, "OneDrive - Test/First")
            make_sharepoint_root(base, "OneDrive - Test/Second")
            controller = StartupController(settings_path=base / "settings.toml")
            with patch("iam_automation.startup.discover_candidates", return_value=discover_candidates((base / "OneDrive - Test",))):
                result = controller.discover_sharepoint()
            self.assertEqual(result.state, StartupState.MULTIPLE_CANDIDATES)
            self.assertFalse(result.ok)

    def test_missing_candidate_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = StartupController(settings_path=Path(tmp) / "settings.toml")
            with patch("iam_automation.startup.discover_candidates", return_value=()):
                result = controller.discover_sharepoint()
            self.assertEqual(result.state, StartupState.NOT_FOUND)
            self.assertFalse(result.ok)

    def test_preflight_is_hard_gate_before_user_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_sharepoint_root(base)
            approved = base / "approved_users.csv"
            approved.write_text("username,roles,active\nDOMAIN\\user,REQUESTER,true\n", encoding="utf-8")
            config_path = base / "config.toml"
            config_path.write_text(
                f'[paths]\nworkspace_path = "{base / "workspace"}"\n'
                '[security]\napproved_users_path = "approved_users.csv"\n',
                encoding="utf-8",
            )
            settings_path = base / "settings.toml"
            controller = StartupController(config_path=config_path, settings_path=settings_path)
            with patch.dict("os.environ", {"IAM_SHAREPOINT_ROOT_PATH": str(root), "IAM_DEV_AUTO_APPROVE_USERS": "0"}, clear=False), patch(
                "iam_automation.startup.project_runtime_path", return_value=base / "runtime.sqlite"
            ):
                result = controller.discover_sharepoint()
            self.assertEqual(result.state, StartupState.CANDIDATE_FOUND)
            with patch("iam_automation.startup.validate_current_user") as validate_user:
                with self.assertRaises(RuntimeError):
                    controller.continue_to_login()
                validate_user.assert_not_called()
            result = controller.validate_environment()
            self.assertTrue(result.ok)
            with patch.dict("os.environ", {"IAM_DEV_AUTO_APPROVE_USERS": "0"}, clear=False), patch(
                "iam_automation.startup.validate_current_user", side_effect=lambda path: object()
            ) as validate_user:
                controller.continue_to_login()
                validate_user.assert_called_once()

    def test_missing_sharepoint_folders_are_created_after_database_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_sharepoint_root(base)
            (root / "audit").rmdir()
            controller = StartupController(settings_path=base / "settings.toml")
            with patch.dict("os.environ", {"IAM_SHAREPOINT_ROOT_PATH": str(root)}, clear=False), patch(
                "iam_automation.startup.project_runtime_path", return_value=base / "runtime.sqlite"
            ):
                controller.discover_sharepoint()
            result = controller.validate_environment()
            self.assertTrue(result.ok)
            self.assertEqual(result.state, StartupState.READY)
            self.assertTrue((root / "audit").is_dir())
            self.assertTrue((root / "requests" / "pending").is_dir())


if __name__ == "__main__":
    unittest.main()
