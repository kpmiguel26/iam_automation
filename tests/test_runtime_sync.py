from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.runtime_sync import RuntimeDatabaseError, publish_runtime_snapshot, repair_runtime_manifest, sync_runtime_snapshot


def create_runtime(path: Path, value: str = "one") -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO settings (key, value) VALUES ('version', ?)", (value,))
    connection.commit()
    connection.close()


class RuntimeSyncTests(unittest.TestCase):
    def test_sync_copies_valid_snapshot_and_creates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            create_runtime(published)
            local = root / "runtime.sqlite"
            snapshot = sync_runtime_snapshot(published, local)
            self.assertTrue(local.exists())
            self.assertTrue(snapshot.manifest_path.exists())

    def test_sync_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            create_runtime(published)
            sync_runtime_snapshot(published, root / "runtime.sqlite")
            connection = sqlite3.connect(published)
            try:
                connection.execute("INSERT INTO settings (key, value) VALUES ('changed', 'yes')")
                connection.commit()
            finally:
                connection.close()
            connection.close()
            with self.assertRaises(RuntimeDatabaseError):
                sync_runtime_snapshot(published, root / "runtime.sqlite")

    def test_publish_creates_backup_and_enforces_expected_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            create_runtime(published)
            local = root / "runtime.sqlite"
            sync_runtime_snapshot(published, local)
            connection = sqlite3.connect(local)
            try:
                connection.execute("UPDATE settings SET value = 'two' WHERE key = 'version'")
                connection.commit()
            finally:
                connection.close()
            connection.close()
            snapshot = publish_runtime_snapshot(local, published, actor="admin", expected_checksum=snapshot_checksum(published))
            self.assertTrue(snapshot.manifest_path.exists())
            self.assertTrue(any((published.parent / "backups").glob("*.sqlite")))

    def test_manifest_repair_requires_integrity_and_restores_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "database" / "snapshots" / "iam_runtime.sqlite"
            published.parent.mkdir(parents=True)
            create_runtime(published)
            sync_runtime_snapshot(published, root / "first.sqlite")
            manifest = published.with_name("iam_runtime.manifest.json")
            manifest.write_text('{"sha256":"stale"}\n', encoding="utf-8")

            repair_runtime_manifest(published)

            self.assertEqual(sync_runtime_snapshot(published, root / "second.sqlite").checksum, snapshot_checksum(published))


def snapshot_checksum(path: Path) -> str:
    from iam_automation.runtime_sync import sha256_file

    return sha256_file(path)


if __name__ == "__main__":
    unittest.main()
