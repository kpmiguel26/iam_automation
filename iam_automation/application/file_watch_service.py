from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import AppUserModel, FileObservationModel, NotificationModel, UserRoleModel, orm_session
from ..change_request import load_request_file
from .employee_service import EmployeeService
from .notification_service import NotificationService
from .roster_lock_ingestion_service import RosterLockIngestionService
from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter


LOGGER = logging.getLogger(__name__)
_WRITE_LOCK = threading.RLock()


@dataclass(frozen=True)
class FileObservation:
    path: str
    file_kind: str
    signature: str


class FileWatchService:
    """Detect shared changes and stage Roster Lock files safely.

    JSON/configuration changes remain notification-driven. Roster Lock workbooks
    are validated and staged automatically, but promotion into canonical workers
    remains an explicit administrative action.
    """

    def __init__(self, database_path: Path, sharepoint_root: Path):
        self.database_path = database_path
        self.sharepoint_root = sharepoint_root
        self.notifications = NotificationService(database_path)

    def start(self, interval_seconds: float = 1.0) -> "FileWatcher":
        watcher = FileWatcher(self, interval_seconds)
        watcher.start()
        return watcher

    def scan_once(self) -> int:
        observations = self._discover_files()
        if not observations:
            return 0
        with _WRITE_LOCK:
            now = datetime.now(timezone.utc).isoformat()
            changed = self._changed_observations(observations)
            changed.sort(key=self._observation_priority)
            successful_ingestions: set[str] = set()
            for observation in changed:
                if observation.file_kind not in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS", "APPROVED_IMPORT"}:
                    successful_ingestions.add(observation.path)
                    continue
                try:
                    if observation.file_kind == "ROSTER_LOCK":
                        RosterLockIngestionService(self.database_path).ingest_file(Path(observation.path))
                    elif observation.file_kind == "RSR_SUPPLIER_WORKER_DETAILS":
                        RsrSupplierWorkerDetailsAdapter(self.database_path).ingest_file(Path(observation.path))
                    else:
                        self._sync_approved_import(Path(observation.path))
                    successful_ingestions.add(observation.path)
                except Exception as exc:
                    LOGGER.exception("Roster Lock ingestion failed for %s", observation.path)
                    self._record_ingestion_failure(observation, exc)

            # The observation is committed only after ingestion succeeds. A transient
            # OneDrive or SQLite failure is therefore retried on the next poll.
            admins = self._active_admins()
            with orm_session(self.database_path) as session:
                for observation in changed:
                    if observation.path not in successful_ingestions:
                        continue
                    previous = session.get(FileObservationModel, observation.path)
                    stored_kind = "APPROVED_IMPORT_SYNCED" if observation.file_kind == "APPROVED_IMPORT" else observation.file_kind
                    if previous is None:
                        session.add(FileObservationModel(path=observation.path, file_kind=stored_kind, signature=observation.signature, first_seen_at_utc=now, last_seen_at_utc=now))
                    else:
                        previous.signature = observation.signature
                        previous.file_kind = stored_kind
                        previous.last_seen_at_utc = now
                    for username in admins:
                        session.add(self._notification(username, observation))
            return len(successful_ingestions)

    def _changed_observations(self, observations: list[FileObservation]) -> list[FileObservation]:
        with orm_session(self.database_path) as session:
            return [
                observation
                for observation in observations
                if (previous := session.get(FileObservationModel, observation.path)) is None
                or previous.signature != observation.signature
                # Older builds recorded approved requests as generic file
                # observations. Reconcile each of those once after upgrade so
                # employees approved on another workstation appear locally.
                or (observation.file_kind == "APPROVED_IMPORT" and previous.file_kind == "APPROVED_IMPORT")
            ]

    def _record_ingestion_failure(self, observation: FileObservation, error: Exception) -> None:
        admins = self._active_admins()
        with orm_session(self.database_path) as session:
            for username in admins:
                session.merge(NotificationModel(
                    notification_id=hashlib.sha256(f"{username}:{observation.path}:{observation.signature}:failure".encode()).hexdigest(),
                    recipient_username=username,
                    notification_type="INGESTION_ERROR",
                    severity="ERROR",
                    title=f"{observation.file_kind.replace('_', ' ').title()} ingestion failed",
                    message=f"The workbook could not be staged and will be retried: {type(error).__name__}: {error}",
                    entity_type="file",
                    entity_id=observation.path,
                    target_route="/admin/imports",
                    status="UNREAD",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                ))

    def _sync_approved_import(self, path: Path) -> None:
        """Apply a shared approved import to this workstation's local SQLite.

        Approval is shared through JSON, while canonical workers remain local
        until the next runtime publication. This reconciliation makes an
        approval performed on another workstation visible here without making
        every workstation publish its database automatically.
        """
        request = load_request_file(path)
        if request.operation_type not in {"IMPORT_ROSTER_LOCK", "IMPORT_RSR_SUPPLIER_DETAILS"}:
            return
        record_ids = request.payload.get("record_ids", [])
        result = EmployeeService(self.database_path).apply_approved_import_records(record_ids, "shared-approval-sync", request_payload=request.payload)
        if int(result.get("failed", 0)):
            errors = "; ".join(f"{item.get('record_id', '')[:8]}: {item.get('error', 'unknown error')}" for item in result.get("errors", []))
            raise RuntimeError(f"Approved import {request.request_id[:8]} could not be fully synchronized: {errors}")

    @staticmethod
    def _observation_priority(observation: FileObservation) -> int:
        if observation.file_kind != "APPROVED_IMPORT":
            return 0
        try:
            request = load_request_file(Path(observation.path))
            return 1 if request.operation_type == "IMPORT_ROSTER_LOCK" else 2
        except (OSError, ValueError):
            return 3

    def _discover_files(self) -> list[FileObservation]:
        roots = (
            (self.sharepoint_root / "requests" / "pending", "PENDING_REQUEST"),
            (self.sharepoint_root / "config", "CONFIGURATION"),
            (self.sharepoint_root / "database" / "snapshots" / "identity_discoveries", "IDENTITY_DISCOVERY"),
            (self.sharepoint_root / "database" / "snapshots", "PUBLISHED_RUNTIME"),
            (self.sharepoint_root / "rosterlocks", "ROSTER_LOCK"),
            (self.sharepoint_root / "rsrsuplierworkerdetails", "RSR_SUPPLIER_WORKER_DETAILS"),
            (self.sharepoint_root / "requests" / "approved", "APPROVED_IMPORT"),
        )
        observations: list[FileObservation] = []
        for root, kind in roots:
            if not root.is_dir():
                continue
            patterns = ("*.json", "*.toml") if kind == "CONFIGURATION" else (("iam_runtime.sqlite",) if kind == "PUBLISHED_RUNTIME" else (("*.xlsx",) if kind in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"} else ("*.json",)))
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
                    UserRoleModel.role_name.in_(("APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")),
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
            "PUBLISHED_RUNTIME": ("Workspace database updated", "A new published runtime database is available for local refresh."),
            "ROSTER_LOCK": ("Roster Lock ingested", "A vendor Roster Lock workbook was staged for validation and reconciliation."),
            "RSR_SUPPLIER_WORKER_DETAILS": ("RSR worker details ingested", "Supplier worker details were staged for matching against canonical employees."),
            "APPROVED_IMPORT": ("Approved import synchronized", "An approved import was applied to this workstation's local employee database."),
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
            target_route=("/admin/approvals" if observation.file_kind == "PENDING_REQUEST" else "/dashboard" if observation.file_kind == "PUBLISHED_RUNTIME" else "/admin/imports" if observation.file_kind in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"} else "/admin"),
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
            except Exception:
                # The watcher is a long-lived auxiliary process. A bad file, a
                # transient OneDrive state, or a database contention must not kill it.
                LOGGER.exception("File watcher cycle failed; retrying on next poll")
            self._stop.wait(self.interval_seconds)
