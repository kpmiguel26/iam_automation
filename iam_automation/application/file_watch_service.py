from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import AppUserModel, FileObservationModel, UserRoleModel, orm_session
from .notification_service import NotificationService


@dataclass(frozen=True)
class FileObservation:
    path: str
    file_kind: str
    signature: str


class FileWatchService:
    """Detect new or changed inbound JSON/config files and notify administrators.

    The watcher observes only; it never imports or executes a file automatically.
    An administrator must open the target workflow and explicitly process it.
    """

    def __init__(self, database_path: Path, sharepoint_root: Path):
        self.database_path = database_path
        self.sharepoint_root = sharepoint_root
        self.notifications = NotificationService(database_path)

    def start(self, interval_seconds: float = 3.0) -> "FileWatcher":
        watcher = FileWatcher(self, interval_seconds)
        watcher.start()
        return watcher

    def scan_once(self) -> int:
        observations = self._discover_files()
        if not observations:
            return 0
        admins = self._active_admins()
        created = 0
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            for observation in observations:
                previous = session.get(FileObservationModel, observation.path)
                changed = previous is None or previous.signature != observation.signature
                if previous is None:
                    session.add(FileObservationModel(path=observation.path, file_kind=observation.file_kind, signature=observation.signature, first_seen_at_utc=now, last_seen_at_utc=now))
                else:
                    previous.signature = observation.signature
                    previous.file_kind = observation.file_kind
                    previous.last_seen_at_utc = now
                if changed:
                    created += 1
                    for username in admins:
                        session.add(self._notification(username, observation))
        return created

    def _discover_files(self) -> list[FileObservation]:
        roots = (
            (self.sharepoint_root / "requests" / "pending", "PENDING_REQUEST"),
            (self.sharepoint_root / "config", "CONFIGURATION"),
            (self.sharepoint_root / "database" / "snapshots" / "identity_discoveries", "IDENTITY_DISCOVERY"),
        )
        observations: list[FileObservation] = []
        for root, kind in roots:
            if not root.is_dir():
                continue
            patterns = ("*.json", "*.toml") if kind == "CONFIGURATION" else ("*.json",)
            for pattern in patterns:
                for path in root.glob(pattern):
                    if path.is_file() and not path.name.startswith("."):
                        stat = path.stat()
                        signature = hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
                        observations.append(FileObservation(str(path), kind, signature))
        return observations

    def _active_admins(self) -> tuple[str, ...]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(
                select(AppUserModel).join(UserRoleModel).where(
                    AppUserModel.active.is_(True),
                    AppUserModel.status == "ACTIVE",
                    UserRoleModel.role_name.in_(("APPLICATION_ADMIN", "MASTER_ADMIN", "ADMINISTRATOR")),
                )
            ).all()
            return tuple(sorted({row.username for row in rows}))

    @staticmethod
    def _notification(username: str, observation: FileObservation):
        from ..infrastructure.sqlite.orm import NotificationModel

        labels = {
            "PENDING_REQUEST": ("New request file detected", "A new JSON request is waiting in the pending folder."),
            "CONFIGURATION": ("Configuration file detected", "A configuration file changed and is ready for review."),
            "IDENTITY_DISCOVERY": ("Identity discovery updated", "A workstation identity record is available for administrative review."),
        }
        title, message = labels[observation.file_kind]
        now = datetime.now(timezone.utc).isoformat()
        return NotificationModel(
            notification_id=hashlib.sha256(f"{username}:{observation.path}:{observation.signature}".encode()).hexdigest(),
            recipient_username=username,
            notification_type="FILE_DETECTED",
            severity="WARNING" if observation.file_kind != "CONFIGURATION" else "INFO",
            title=title,
            message=f"{message} File: {Path(observation.path).name}",
            entity_type="file",
            entity_id=observation.path,
            target_route="/admin/approvals" if observation.file_kind == "PENDING_REQUEST" else "/admin",
            status="UNREAD",
            created_at_utc=now,
        )


class FileWatcher:
    def __init__(self, service: FileWatchService, interval_seconds: float):
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="iam-file-watcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.service.scan_once()
            except (OSError, RuntimeError):
                # The next polling cycle will retry if OneDrive is temporarily unavailable.
                pass
            self._stop.wait(self.interval_seconds)
