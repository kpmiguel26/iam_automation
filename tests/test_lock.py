from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.lock import LockConflict, acquire_lock, release_lock


class LockTests(unittest.TestCase):
    def test_second_lock_is_rejected_until_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "iam.lock.json"
            first = acquire_lock(
                lock_path,
                user="first",
                computer="pc1",
                operation="write",
                database_checksum="abc",
                database_version="1",
                application_version="test",
            )
            with self.assertRaises(LockConflict):
                acquire_lock(
                    lock_path,
                    user="second",
                    computer="pc2",
                    operation="write",
                    database_checksum="abc",
                    database_version="1",
                    application_version="test",
                )
            self.assertTrue(release_lock(lock_path, first.lock_id))
            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
