"""
File: tests/test_settings_store.py
Purpose: Provides automated regression tests for test settings store.
Responsibilities: Exposes or coordinates: SettingsStoreTests.
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

from iam_automation import settings_store


class SettingsStoreTests(unittest.TestCase):
    def test_toml_reader_uses_text_loads_for_python310_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.toml"
            path.write_text("[paths]\nsharepoint_root_path = \"C:/OneDrive/IAM\"\n", encoding="utf-8")

            class Parser:
                @staticmethod
                def loads(value):
                    self.assertIsInstance(value, str)
                    return {"paths": {"sharepoint_root_path": "C:/OneDrive/IAM"}}

                @staticmethod
                def load(_value):
                    raise AssertionError("binary load must not be used")

            with patch.object(settings_store, "tomllib", Parser):
                values = settings_store.load_user_settings(path)

        self.assertEqual(values["paths"]["sharepoint_root_path"], "C:/OneDrive/IAM")


if __name__ == "__main__":
    unittest.main()
#endfile
