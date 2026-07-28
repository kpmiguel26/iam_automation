from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from sqlalchemy import func, select

from ..database import initialize_runtime_database
from ..runtime_sync import RuntimeDatabaseError, sha256_file, sync_runtime_snapshot
from ..infrastructure.sqlite.orm import PublicationQueueModel, orm_session
from .request_service import RequestService


PUBLISHED_SOURCE_CHECKSUM_KEY = "published_source_checksum"


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


@dataclass(frozen=True)
class WorkspaceVersion:
    published_checksum: str | None
    local_checksum: str | None

    @property
    def update_available(self) -> bool:
        return bool(self.published_checksum and self.local_checksum and self.published_checksum != self.local_checksum)


class WorkspaceRefreshService:
    def __init__(self, local_runtime_path: Path, published_runtime_path: Path, sharepoint_root: Path):
        self.local_runtime_path = local_runtime_path
        self.published_runtime_path = published_runtime_path
        self.sharepoint_root = sharepoint_root

    def version(self) -> WorkspaceVersion:
        published = sha256_file(self.published_runtime_path) if self.published_runtime_path.is_file() else None
        local = None
        if self.local_runtime_path.is_file():
            local = read_published_source_checksum(self.local_runtime_path)
            # Older runtimes have no marker until the next successful refresh.
            if local is None:
                local = sha256_file(self.local_runtime_path)
        return WorkspaceVersion(published, local)

    def refresh(self, username: str) -> tuple[WorkspaceVersion, int]:
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
