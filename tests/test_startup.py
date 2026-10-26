"""
File: tests/test_startup.py
Purpose: Provides automated regression tests for test startup.
Responsibilities: Exposes or coordinates: make_sharepoint_root, StartupTests.
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
import sqlite3
from pathlib import Path
from unittest.mock import patch

from iam_automation.sharepoint_discovery import discover_candidates
from iam_automation.startup import StartupController, StartupState
from iam_automation.settings_store import load_user_settings, save_user_settings


def make_sharepoint_root(base: Path, name: str = "OneDrive - Test/IAMAutomation") -> Path:
    root = base / name
    for folder in ("requests", "audit", "backups"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "database").mkdir(parents=True, exist_ok=True)
    (root / "database" / "snapshots").mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "database" / "snapshots" / "iam_runtime.sqlite")
    connection.execute("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT)")
    connection.commit()
    connection.close()
    return root


class StartupTests(unittest.TestCase):
    def test_corrupt_user_settings_are_backed_up_and_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.toml"
            path.write_text("[paths\ninvalid", encoding="utf-8")
            self.assertEqual(load_user_settings(path), {})
            self.assertFalse(path.exists())
            self.assertEqual(len(tuple(path.parent.glob("settings.toml.corrupt-*"))), 1)

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

    def test_deleted_saved_sharepoint_root_is_recreated_with_basic_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            parent = base / "OneDrive - Test"
            parent.mkdir()
            root = parent / "IAMAutomation"
            settings_path = base / "settings.toml"
            save_user_settings({"paths": {"sharepoint_root_path": str(root)}}, settings_path)
            controller = StartupController(settings_path=settings_path)

            with patch.dict("os.environ", {"IAM_SHAREPOINT_ROOT_PATH": ""}, clear=False):
                discovered = controller.discover_sharepoint()
            self.assertEqual(discovered.state, StartupState.CANDIDATE_FOUND)
            self.assertTrue(root.is_dir())

            result = controller.validate_environment()
            self.assertTrue(result.ok)
            self.assertTrue((root / "database" / "snapshots" / "iam_runtime.sqlite").is_file())
            for relative in (
                "database/snapshots/identity_discoveries",
                "database/snapshots/windows_traceability",
                "requests/pending",
                "audit",
                "backups",
                "reports",
                "templates",
                "generated_templates",
            ):
                self.assertTrue((root / relative).is_dir(), relative)
            self.assertEqual(list((root / "reports").iterdir()), [])

    def test_empty_sharepoint_folder_gets_an_empty_runtime_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "OneDrive - Test" / "IAMAutomation"
            root.mkdir(parents=True)
            controller = StartupController(settings_path=base / "settings.toml")
            with patch.dict("os.environ", {"IAM_SHAREPOINT_ROOT_PATH": str(root)}, clear=False), patch(
                "iam_automation.startup.project_runtime_path", return_value=base / "runtime.sqlite"
            ):
                self.assertEqual(controller.discover_sharepoint().state, StartupState.CANDIDATE_FOUND)
                result = controller.validate_environment()

            self.assertTrue(result.ok)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            self.assertTrue(published.is_file())
            connection = sqlite3.connect(published)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM workers").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM app_users").fetchone()[0], 0)
            finally:
                connection.close()

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
            with patch("iam_automation.identity.validate_current_user") as validate_user:
                with self.assertRaises(RuntimeError):
                    controller.continue_to_login()
                validate_user.assert_not_called()
            result = controller.validate_environment()
            self.assertTrue(result.ok)
            with patch("iam_automation.identity.validate_current_user") as validate_user, patch("iam_automation.startup.windows_username", return_value="DOMAIN\\user"), patch("iam_automation.startup.computer_name", return_value="VDI-01"):
                user = controller.continue_to_login()
                validate_user.assert_not_called()
            self.assertEqual(user.roles, ())
            self.assertEqual(user.username, "DOMAIN\\user")
            audit_files = tuple((root / "audit").glob("audit_*.jsonl"))
            self.assertEqual(len(audit_files), 1)
            self.assertIn("WINDOWS_IDENTITY_RECORDED", audit_files[0].read_text(encoding="utf-8"))

    def test_shared_traceability_write_failure_does_not_block_login_or_admin_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_sharepoint_root(base)
            runtime_path = base / "local-runtime.sqlite"
            controller = StartupController(settings_path=base / "settings.toml")
            with patch.dict("os.environ", {"IAM_SHAREPOINT_ROOT_PATH": str(root)}, clear=False), patch(
                "iam_automation.startup.project_runtime_path", return_value=runtime_path
            ):
                self.assertTrue(controller.discover_sharepoint().ok)
                self.assertTrue(controller.validate_environment().ok)
                with patch("iam_automation.startup.sys.platform", "win32"), patch(
                    "iam_automation.startup.windows_username", return_value="DOMAIN\\user"
                ), patch("iam_automation.startup.computer_name", return_value="VDI-01"), patch(
                    "iam_automation.startup.record_windows_traceability", side_effect=FileNotFoundError("OneDrive sync race")
                ):
                    user = controller.continue_to_login()

            self.assertEqual(user.username, "DOMAIN\\user")
            connection = sqlite3.connect(runtime_path)
            try:
                roles = connection.execute(
                    "SELECT role_name FROM user_roles WHERE username = ?", ("DOMAIN\\user",)
                ).fetchall()
                self.assertIn(("MASTER_ADMIN",), roles)
            finally:
                connection.close()

    def test_missing_sharepoint_folders_are_created_after_database_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_sharepoint_root(base)
            (root / "audit").rmdir()
            controller = StartupController(settings_path=base / "settings.toml")
            with patch.dict(
                "os.environ",
                {"IAM_SHAREPOINT_ROOT_PATH": str(root), "IAM_WORKSPACE_PATH": str(base / "workspace")},
                clear=False,
            ), patch(
                "iam_automation.startup.project_runtime_path", return_value=base / "runtime.sqlite"
            ):
                controller.discover_sharepoint()
            result = controller.validate_environment()
            self.assertTrue(result.ok)
            self.assertEqual(result.state, StartupState.READY)
            self.assertTrue((root / "audit").is_dir())
            self.assertTrue((root / "requests" / "pending").is_dir())
            self.assertTrue((root / "database" / "snapshots" / "identity_discoveries").is_dir())
            self.assertTrue((root / "database" / "snapshots" / "windows_traceability").is_dir())


if __name__ == "__main__":
    unittest.main()
#endfile
