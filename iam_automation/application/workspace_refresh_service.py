from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from ..database import initialize_runtime_database
from ..runtime_sync import RuntimeDatabaseError, sha256_file, sync_runtime_snapshot
from ..infrastructure.sqlite.orm import PublicationQueueModel, orm_session
from .request_service import RequestService


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
        local = sha256_file(self.local_runtime_path) if self.local_runtime_path.is_file() else None
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
        return self.version(), exported
