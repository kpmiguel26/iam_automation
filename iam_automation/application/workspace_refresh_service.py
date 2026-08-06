from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import threading

from sqlalchemy import func, select

from ..database import initialize_runtime_database
from ..runtime_sync import RuntimeDatabaseError, runtime_manifest_path, sha256_file, sync_runtime_snapshot
from ..infrastructure.sqlite.orm import PublicationQueueModel, orm_session
from .request_service import RequestService


PUBLISHED_SOURCE_CHECKSUM_KEY = "published_source_checksum"
LOCAL_RUNTIME_CHECKSUM_SUFFIX = ".source-checksum"
WORKSPACE_IO_LOCK = threading.RLock()
_LOCAL_CHECKSUM_CACHE: dict[str, tuple[int, int, str]] = {}


def local_runtime_checksum_path(database_path: Path) -> Path:
    return database_path.with_name(database_path.name + LOCAL_RUNTIME_CHECKSUM_SUFFIX)


def record_published_source_checksum(database_path: Path, checksum: str) -> None:
    """Record the published snapshot applied to a migrated local runtime."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            INSERT INTO app_metadata (metadata_key, metadata_value, updated_at_utc)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(metadata_key) DO UPDATE SET
                metadata_value = excluded.metadata_value,
                updated_at_utc = excluded.updated_at_utc
            """,
            (PUBLISHED_SOURCE_CHECKSUM_KEY, checksum),
        )
        connection.commit()
    finally:
        connection.close()
    # The SQLite metadata row records the published baseline, while this
    # sidecar records the exact local bytes after that bookkeeping update.
    # Comparing the sidecar to the current file detects later local edits.
    record_local_runtime_checksum(database_path)


def record_local_runtime_checksum(database_path: Path) -> None:
    """Record the current local bytes after an expected internal write."""
    sidecar = local_runtime_checksum_path(database_path)
    temporary = sidecar.with_suffix(sidecar.suffix + ".tmp")
    temporary.write_text(sha256_file(database_path) + "\n", encoding="utf-8")
    temporary.replace(sidecar)


def read_published_source_checksum(database_path: Path) -> str | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT metadata_value FROM app_metadata WHERE metadata_key = ?",
            (PUBLISHED_SOURCE_CHECKSUM_KEY,),
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        connection.close()


def _published_manifest_checksum(database_path: Path) -> str | None:
    manifest_path = runtime_manifest_path(database_path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    checksum = payload.get("sha256")
    return str(checksum) if isinstance(checksum, str) and checksum else None


def _cached_checksum(database_path: Path) -> str:
    stat = database_path.stat()
    key = str(database_path)
    signature = (stat.st_size, stat.st_mtime_ns)
    cached = _LOCAL_CHECKSUM_CACHE.get(key)
    if cached and cached[:2] == signature:
        return cached[2]
    checksum = sha256_file(database_path)
    _LOCAL_CHECKSUM_CACHE[key] = (signature[0], signature[1], checksum)
    return checksum


@dataclass(frozen=True)
class WorkspaceVersion:
    published_checksum: str | None
    local_checksum: str | None
    local_dirty: bool = False

    @property
    def update_available(self) -> bool:
        return bool(self.local_dirty or (self.published_checksum and self.local_checksum and self.published_checksum != self.local_checksum))


class WorkspaceRefreshService:
    def __init__(self, local_runtime_path: Path, published_runtime_path: Path, sharepoint_root: Path):
        self.local_runtime_path = local_runtime_path
        self.published_runtime_path = published_runtime_path
        self.sharepoint_root = sharepoint_root

    def version(self) -> WorkspaceVersion:
        acquired = WORKSPACE_IO_LOCK.acquire(timeout=0.25)
        if not acquired:
            # A large source ingestion may hold the lock for a while. Do not
            # make login/dashboard wait behind it; the next status poll will
            # observe the complete version after the writer releases it.
            return self._version_without_lock()
        try:
            published = _published_manifest_checksum(self.published_runtime_path) if self.published_runtime_path.is_file() else None
            if published is None and self.published_runtime_path.is_file():
                published = _cached_checksum(self.published_runtime_path)
            local = None
            local_dirty = False
            if self.local_runtime_path.is_file():
                local = read_published_source_checksum(self.local_runtime_path)
                # Older runtimes have no marker until the next successful refresh.
                if local is None:
                    local = _cached_checksum(self.local_runtime_path)
                else:
                    sidecar = local_runtime_checksum_path(self.local_runtime_path)
                    if sidecar.is_file():
                        recorded = sidecar.read_text(encoding="utf-8").strip()
                        local_dirty = recorded != _cached_checksum(self.local_runtime_path)
            return WorkspaceVersion(published, local, local_dirty)
        finally:
            WORKSPACE_IO_LOCK.release()

    def _version_without_lock(self) -> WorkspaceVersion:
        """Return a safe lightweight status while the watcher owns the lock."""
        published = _published_manifest_checksum(self.published_runtime_path) if self.published_runtime_path.is_file() else None
        local = None
        if self.local_runtime_path.is_file():
            try:
                local = read_published_source_checksum(self.local_runtime_path)
            except (OSError, sqlite3.Error):
                local = None
        return WorkspaceVersion(published, local, False)

    def refresh(self, username: str) -> tuple[WorkspaceVersion, int]:
        with WORKSPACE_IO_LOCK:
            pending_folder = self.sharepoint_root / "requests" / "pending"
            exported = RequestService(self.local_runtime_path).export_pending_for_user(username, pending_folder)
            with orm_session(self.local_runtime_path) as session:
                pending_publications = int(session.scalar(select(func.count(PublicationQueueModel.publication_id)).where(PublicationQueueModel.status == "PENDING_PUBLICATION")) or 0)
            if pending_publications:
                raise RuntimeDatabaseError("Refresh is blocked while local publications are pending. Publish or resolve them first.")
            snapshot = sync_runtime_snapshot(self.published_runtime_path, self.local_runtime_path)
            initialize_runtime_database(snapshot.local_path)
            record_published_source_checksum(snapshot.local_path, snapshot.checksum)
            return self.version(), exported
