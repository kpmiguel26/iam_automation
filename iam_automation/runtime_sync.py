"""
File: iam_automation/runtime_sync.py
Purpose: Provides the runtime sync component of IAM Automation.
Responsibilities: Exposes or coordinates: RuntimeDatabaseError, RuntimeSnapshot, project_runtime_path, runtime_manifest_path, find_published_runtime_db, find_published_access_db, ….
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_FILENAME = "iam_runtime.sqlite"
RUNTIME_MANIFEST_FILENAME = "iam_runtime.manifest.json"
RUNTIME_RELATIVE_PATH = Path("database") / "snapshots" / RUNTIME_FILENAME


class RuntimeDatabaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSnapshot:
    published_path: Path
    manifest_path: Path
    local_path: Path
    checksum: str
    schema_version: str
    published_at_utc: str


def project_runtime_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[1]
    return root / "runtime.sqlite"


def runtime_manifest_path(published_path: Path) -> Path:
    return published_path.with_name(RUNTIME_MANIFEST_FILENAME)


def find_published_runtime_db(root: Path) -> Path | None:
    preferred = root / RUNTIME_RELATIVE_PATH
    if preferred.is_file():
        return preferred
    matches = tuple(sorted(path for path in root.rglob("*.sqlite") if path.is_file() and path.name != "runtime.sqlite"))
    return matches[0] if len(matches) == 1 else None


def find_published_access_db(root: Path) -> Path | None:
    preferred = root / "database" / "iam_automation.accdb"
    if preferred.is_file():
        return preferred
    matches = tuple(sorted(path for path in root.rglob("*.accdb") if path.is_file()))
    return matches[0] if len(matches) == 1 else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_runtime_database(path: Path) -> None:
    if not path.is_file():
        raise RuntimeDatabaseError(f"Runtime SQLite database was not found: {path}")
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeDatabaseError(f"SQLite integrity check failed: {path}")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeDatabaseError(f"Runtime SQLite database could not be opened: {path}: {exc}") from exc


def checkpoint_runtime_database(path: Path) -> None:
    """Flush SQLite WAL content before hashing or copying a runtime snapshot."""
    try:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeDatabaseError(f"SQLite WAL checkpoint failed: {path}: {exc}") from exc


def _atomic_replace_with_retry(temporary: Path, destination: Path, *, attempts: int = 8) -> None:
    """Replace a SQLite snapshot while tolerating short Windows file locks."""
    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(0.25)
    if last_error is not None:
        raise last_error


def _remove_temporary_sqlite_files(temporary: Path) -> None:
    """Remove a temporary database and any SQLite sidecars left by validation."""
    for path in (temporary, temporary.with_name(temporary.name + "-wal"), temporary.with_name(temporary.name + "-shm")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            # A later sync can safely retry cleanup; never hide the main result.
            pass


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_or_create_manifest(published_path: Path, manifest_path: Path) -> dict[str, Any]:
    checksum = sha256_file(published_path)
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeDatabaseError(f"Runtime manifest is invalid: {manifest_path}") from exc
        if manifest.get("sha256") != checksum:
            raise RuntimeDatabaseError("Runtime SQLite checksum does not match its manifest.")
        return manifest
    manifest = {
        "file": published_path.name,
        "sha256": checksum,
        "schema_version": "1.0.0",
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_by": "IAM Automation startup bootstrap",
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest


def repair_runtime_manifest(published_path: Path, *, generated_by: str = "IAM Automation explicit manifest repair") -> Path:
    """Rebuild a manifest only after the published SQLite passes integrity checks."""
    published_path = published_path.expanduser().resolve()
    manifest_path = runtime_manifest_path(published_path)
    checkpoint_runtime_database(published_path)
    validate_runtime_database(published_path)
    previous: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    payload = {
        "file": published_path.name,
        "sha256": sha256_file(published_path),
        "schema_version": str(previous.get("schema_version", "1.0.0")),
        "published_at_utc": str(previous.get("published_at_utc", "")) or datetime.now(timezone.utc).isoformat(),
        "generated_by": generated_by,
        "repaired_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(manifest_path, payload)
    return manifest_path


def sync_runtime_snapshot(published_path: Path, local_path: Path | None = None) -> RuntimeSnapshot:
    """Validate and atomically copy the published SQLite snapshot into the project root."""
    local = local_path or project_runtime_path()
    manifest_path = runtime_manifest_path(published_path)
    checkpoint_runtime_database(published_path)
    validate_runtime_database(published_path)
    manifest = _load_or_create_manifest(published_path, manifest_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists():
        backup_folder = local.parent / "runtime_backups"
        backup_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, backup_folder / f"runtime_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.sqlite")
    temporary = local.with_name(f".{local.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(published_path, temporary)
        validate_runtime_database(temporary)
        _atomic_replace_with_retry(temporary, local)
    finally:
        _remove_temporary_sqlite_files(temporary)
    return RuntimeSnapshot(published_path, manifest_path, local, str(manifest["sha256"]), str(manifest.get("schema_version", "unknown")), str(manifest.get("published_at_utc", "")))


def publish_runtime_snapshot(local_path: Path, published_path: Path, *, actor: str, expected_checksum: str | None = None) -> RuntimeSnapshot:
    """Publish an admin-edited local SQLite snapshot with backup and optimistic concurrency."""
    checkpoint_runtime_database(local_path)
    validate_runtime_database(local_path)
    if published_path.exists() and expected_checksum and sha256_file(published_path) != expected_checksum:
        raise RuntimeDatabaseError("Published runtime SQLite changed since it was downloaded.")
    published_path.parent.mkdir(parents=True, exist_ok=True)
    if published_path.exists():
        backup_folder = published_path.parent / "backups"
        backup_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(published_path, backup_folder / f"{published_path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.sqlite")
    temporary = published_path.with_name(f".{published_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(local_path, temporary)
        _atomic_replace_with_retry(temporary, published_path)
    finally:
        _remove_temporary_sqlite_files(temporary)
    checksum = sha256_file(published_path)
    manifest_path = runtime_manifest_path(published_path)
    manifest = {"file": published_path.name, "sha256": checksum, "schema_version": "1.0.0", "published_at_utc": datetime.now(timezone.utc).isoformat(), "published_by": actor}
    _write_json_atomic(manifest_path, manifest)
    return RuntimeSnapshot(published_path, manifest_path, local_path, checksum, "1.0.0", manifest["published_at_utc"])
#endfile
