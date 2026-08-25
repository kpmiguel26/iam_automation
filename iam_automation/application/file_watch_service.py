"""
File: iam_automation/application/file_watch_service.py
Purpose: Implements the application service for file watch service workflows.
Responsibilities: Exposes or coordinates: FileObservation, watcher_health_path, load_watcher_health, FileWatchService, FileWatcher.
Dependencies: sqlalchemy, infrastructure, change_request, identity, employee_service
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
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import AppUserModel, FileObservationModel, NotificationModel, UserRoleModel, orm_session
from ..change_request import load_request_file
from ..identity import CurrentUser, ROLE_REQUESTER, computer_name
from .employee_service import EmployeeService
from .notification_service import NotificationService
from .roster_lock_ingestion_service import RosterLockIngestionService
from .accessnow_ingestion_service import AccessNowIngestionService
from .shared_request_service import SharedRequestService
from .workspace_refresh_service import WORKSPACE_IO_LOCK, local_runtime_checksum_path, record_local_runtime_checksum
from .stable_file_read import read_stable_bytes
from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter


LOGGER = logging.getLogger(__name__)
EXPECTED_INGESTION_ERRORS = (OSError, PermissionError, ValueError, RuntimeError)


@dataclass(frozen=True)
class FileObservation:
    path: str
    file_kind: str
    signature: str


def watcher_health_path(database_path: Path) -> Path:
    """Return the local, non-published watcher health sidecar path."""
    return database_path.with_name(database_path.name + ".watcher-health.json")


def load_watcher_health(database_path: Path) -> dict[str, object]:
    """Read the last watcher state without making health part of SQLite data."""
    path = watcher_health_path(database_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


class FileWatchService:
    """Detect shared changes and stage source reports safely.

    JSON/configuration changes remain notification-driven. Source workbooks and
    AccessNow reports
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

    def record_watcher_health(
        self,
        *,
        status: str,
        consecutive_failures: int,
        processed_count: int = 0,
        error: Exception | None = None,
    ) -> None:
        """Persist operational watcher state outside the shared runtime DB."""
        now = datetime.now(timezone.utc).isoformat()
        previous = load_watcher_health(self.database_path)
        payload = {
            "status": status,
            "last_cycle_at_utc": now,
            "last_success_at_utc": now if status == "HEALTHY" else previous.get("last_success_at_utc"),
            "consecutive_failures": max(0, int(consecutive_failures)),
            "last_processed_count": max(0, int(processed_count)),
            "last_error": f"{type(error).__name__}: {error}" if error else "",
        }
        path = watcher_health_path(self.database_path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def scan_once(self) -> int:
        # Refresh replaces the local SQLite file atomically. Hold the same
        # process-wide lock across discovery and ingestion so a checksum/read,
        # SQLite connection, and file replacement cannot overlap.
        with WORKSPACE_IO_LOCK:
            observations = self._discover_files()
            if not observations:
                return 0
            # The watcher itself writes observations and notifications to the
            # local runtime. Preserve a genuine user edit, but advance the
            # sidecar after an automatic scan that started from a clean state.
            sidecar = local_runtime_checksum_path(self.database_path)
            watcher_started_clean = sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() == hashlib.sha256(self.database_path.read_bytes()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            changed = self._changed_observations(observations)
            changed.sort(key=self._observation_priority)
            successful_ingestions: set[str] = set()
            review_requests: set[str] = set()
            accessnow_processed = False
            for observation in changed:
                if observation.file_kind not in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS", "ACCESSNOW", "APPROVED_IMPORT"}:
                    successful_ingestions.add(observation.path)
                    continue
                try:
                    if observation.file_kind == "ROSTER_LOCK":
                        result = RosterLockIngestionService(self.database_path).ingest_file(Path(observation.path))
                        self._ensure_import_review_request(observation, result)
                        review_requests.add(observation.path)
                    elif observation.file_kind == "RSR_SUPPLIER_WORKER_DETAILS":
                        result = RsrSupplierWorkerDetailsAdapter(self.database_path).ingest_file(Path(observation.path))
                        self._ensure_import_review_request(observation, result)
                        review_requests.add(observation.path)
                    elif observation.file_kind == "ACCESSNOW":
                        if accessnow_processed:
                            successful_ingestions.add(observation.path)
                            continue
                        result = AccessNowIngestionService(self.database_path).ingest_folder(self.sharepoint_root / "acessnow")
                        self._ensure_import_review_request(observation, result)
                        accessnow_processed = True
                        review_requests.update(item.path for item in changed if item.file_kind == "ACCESSNOW")
                    else:
                        self._sync_approved_import(Path(observation.path))
                        # The approval JSON is only a shared signal. It must not
                        # create a generic file alert or imply that canonical
                        # employees were already updated.
                        review_requests.add(observation.path)
                    successful_ingestions.add(observation.path)
                except EXPECTED_INGESTION_ERRORS as exc:
                    # These are normal operational failures (partial sync,
                    # invalid input, or an unavailable optional dependency).
                    # Leave the observation uncommitted so the next scan retries it.
                    LOGGER.warning("File processing will be retried for %s: %s", observation.path, exc)
                    self._record_ingestion_failure(observation, exc, unexpected=False)
                except Exception as exc:
                    # Keep the watcher alive at this process boundary, but make
                    # programming/data-layer failures distinguishable from a
                    # normal retry in the admin notification.
                    LOGGER.exception("Unexpected file processing failure for %s", observation.path)
                    self._record_ingestion_failure(observation, exc, unexpected=True)

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
                    if observation.path not in review_requests:
                        for username in admins:
                            # File notifications use a deterministic ID so a
                            # repeated scan cannot create duplicates. Preserve
                            # an existing READ/RESOLVED status on retry.
                            notification = self._notification(username, observation)
                            if session.get(NotificationModel, notification.notification_id) is None:
                                session.add(notification)
            # Roster Lock can reveal a rehire hold as soon as the source file
            # is staged. The deterministic notification is safe to repeat.
            self.notifications.notify_rehire_alerts(EmployeeService(self.database_path).rehire_alerts())
            if watcher_started_clean:
                record_local_runtime_checksum(self.database_path)
            return len(successful_ingestions)

    def _ensure_import_review_request(self, observation: FileObservation, result) -> None:
        """Create the shared approval request for a newly staged workbook.

        Staging is safe to repeat, so this method also runs when an observation
        is retried after a temporary SQLite or OneDrive failure.  Batch ID and
        content checksum make the shared request idempotent across workstations.
        """
        batch_id = str(result.batch_id)
        source_path = Path(observation.path)
        source_checksum = str(getattr(result, "source_checksum", "")) or hashlib.sha256(read_stable_bytes(source_path)).hexdigest()
        source_filename = str(getattr(result, "filename", source_path.name))
        shared = SharedRequestService(self.sharepoint_root)
        existing = shared.find_import_request(batch_id=batch_id, source_checksum=source_checksum)
        if existing is not None:
            # A reset or a second workstation may already have the shared JSON.
            # Re-publish the idempotent notification so the local admin still
            # sees the review work without creating another request.
            self.notifications.notify_request_reviewers(
                existing.request_id,
                existing.operation_type,
                existing.created_by,
                record_count=int((existing.payload or {}).get("record_count", 0)),
            )
            return

        source_system = observation.file_kind
        staged = [
            item for item in EmployeeService(self.database_path).list_staged_records()
            if str(item.get("batch_id", "")) == batch_id
            and str(item.get("source_system", "")) == source_system
        ]
        record_ids = [str(item["record_id"]) for item in staged]
        operation_type = (
            "IMPORT_RSR_SUPPLIER_DETAILS"
            if source_system == "RSR_SUPPLIER_WORKER_DETAILS"
            else "IMPORT_ACCESSNOW" if source_system == "ACCESSNOW" else "IMPORT_ROSTER_LOCK"
        )
        payload = {
            "batch_ids": [batch_id],
            "record_ids": record_ids,
            "record_count": len(record_ids),
            "source_system": source_system,
            "source_file": source_filename,
            "source_checksum": source_checksum,
            "total_rows": int(result.total_rows),
            "staged_rows": int(result.staged_rows),
            "quarantine_rows": int(getattr(result, "quarantine_rows", getattr(result, "quarantined_rows", 0))),
            "record_previews": EmployeeService(self.database_path).request_previews(record_ids),
        }
        actor = CurrentUser("workspace-watcher", computer_name(), (ROLE_REQUESTER,))
        reason = (
            f"Review newly discovered {source_system.replace('_', ' ').title()} file "
            f"before applying {len(record_ids)} staged record(s) to canonical employees."
        )
        request = shared.create(actor, operation_type, batch_id, payload, reason)
        self.notifications.notify_request_reviewers(
            request.request_id,
            operation_type,
            actor.username,
            record_count=len(record_ids),
        )

    def _changed_observations(self, observations: list[FileObservation]) -> list[FileObservation]:
        with orm_session(self.database_path) as session:
            return [
                observation
                for observation in observations
                if (previous := session.get(FileObservationModel, observation.path)) is None
                or previous.signature != observation.signature
            ]

    def _record_ingestion_failure(self, observation: FileObservation, error: Exception, *, unexpected: bool) -> None:
        admins = self._active_admins()
        with orm_session(self.database_path) as session:
            for username in admins:
                session.merge(NotificationModel(
                    notification_id=hashlib.sha256(f"{username}:{observation.path}:{observation.signature}:failure".encode()).hexdigest(),
                    recipient_username=username,
                    notification_type="INGESTION_ERROR",
                    severity="ERROR",
                    title=f"{observation.file_kind.replace('_', ' ').title()} {'unexpected failure' if unexpected else 'ingestion failed'}",
                    message=f"The workbook could not be staged and will be retried: {type(error).__name__}: {error}",
                    entity_type="file",
                    entity_id=observation.path,
                    target_route="/admin/imports",
                    status="UNREAD",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                ))

    def _sync_approved_import(self, path: Path) -> None:
        """Register an approved source file for individual review.

        Approval JSON is a shared signal, not permission to bulk-write every
        row into the local canonical database. Promotion happens one employee
        at a time from Source Updates, where matching, history, and business
        rules are visible to the reviewer.
        """
        request = load_request_file(path)
        if request.operation_type not in {"IMPORT_ROSTER_LOCK", "IMPORT_RSR_SUPPLIER_DETAILS", "IMPORT_ACCESSNOW"}:
            return
        self.notifications.notify_source_update_available(
            request.request_id,
            request.operation_type,
            int(request.payload.get("record_count", len(request.payload.get("record_ids", [])))),
        )

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
            (self.sharepoint_root / "acessnow", "ACCESSNOW"),
            (self.sharepoint_root / "requests" / "approved", "APPROVED_IMPORT"),
        )
        observations: list[FileObservation] = []
        for root, kind in roots:
            if not root.is_dir():
                continue
            patterns = ("*.json", "*.toml") if kind == "CONFIGURATION" else (("iam_runtime.sqlite",) if kind == "PUBLISHED_RUNTIME" else (("*.xlsx", "*.csv") if kind == "ACCESSNOW" else (("*.xlsx",) if kind in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"} else ("*.json",))))
            for pattern in patterns:
                for path in root.glob(pattern):
                    if path.is_file() and not path.name.startswith("."):
                        # Metadata-only signatures miss in-place edits that
                        # preserve size and timestamp resolution. The content
                        # checksum is also the identity used by ingestion,
                        # so the watcher and source pipeline now agree.
                        signature = hashlib.sha256(read_stable_bytes(path)).hexdigest()
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

    def record_watcher_failure(self, error: Exception, consecutive_failures: int) -> None:
        """Notify administrators when the watcher remains unhealthy."""
        if consecutive_failures < 3:
            return
        fingerprint = hashlib.sha256(f"{type(error).__name__}:{error}".encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        admins = self._active_admins()
        with orm_session(self.database_path) as session:
            for username in admins:
                notification_id = hashlib.sha256(f"watcher-cycle:{username}:{fingerprint}".encode("utf-8")).hexdigest()
                notification = session.get(NotificationModel, notification_id)
                if notification is None:
                    session.add(NotificationModel(
                        notification_id=notification_id,
                        recipient_username=username,
                        notification_type="WATCHER_CYCLE_FAILURE",
                        severity="CRITICAL",
                        title="File watcher is repeatedly failing",
                        message=f"The watcher has failed {consecutive_failures} consecutive cycle(s) and will keep retrying: {type(error).__name__}: {error}",
                        entity_type="file_watcher",
                        entity_id="iam-file-watcher",
                        target_route="/admin/imports",
                        status="UNREAD",
                        created_at_utc=now,
                    ))
                elif notification.status in {"RESOLVED", "EXPIRED"}:
                    notification.status = "UNREAD"
                    notification.read_at_utc = None

    def record_watcher_recovery(self) -> None:
        """Resolve open watcher failure notifications after a healthy cycle."""
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(NotificationModel).where(
                NotificationModel.notification_type == "WATCHER_CYCLE_FAILURE",
                NotificationModel.status.in_(("UNREAD", "READ")),
            )).all()
            for row in rows:
                row.status = "RESOLVED"

    @staticmethod
    def _notification(username: str, observation: FileObservation):
        from ..infrastructure.sqlite.orm import NotificationModel

        labels = {
            "PENDING_REQUEST": ("New request file detected", "A new JSON request is waiting in the pending folder."),
            "CONFIGURATION": ("Configuration file detected", "A configuration file changed and is ready for review."),
            "IDENTITY_DISCOVERY": ("Identity discovery updated", "A workstation identity record is available for administrative review."),
            "PUBLISHED_RUNTIME": ("New database snapshot published", "A new runtime SQLite snapshot is available. Refresh this workstation when you are not editing a form."),
            "ROSTER_LOCK": ("Roster Lock ingested", "A vendor Roster Lock workbook was staged for validation and reconciliation."),
            "RSR_SUPPLIER_WORKER_DETAILS": ("RSR worker details ingested", "Supplier worker details were staged for matching against canonical employees."),
            "ACCESSNOW": ("AccessNow reports ingested", "Active and termination reports were merged and staged for employee status review."),
            "APPROVED_IMPORT": ("Employee updates ready", "Approved source records are ready for individual matching and review. No employee was created automatically."),
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
            target_route=("/admin/approvals" if observation.file_kind == "PENDING_REQUEST" else "/dashboard" if observation.file_kind == "PUBLISHED_RUNTIME" else "/employees/source-updates" if observation.file_kind in {"APPROVED_IMPORT", "ACCESSNOW"} else "/admin/imports" if observation.file_kind in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"} else "/admin"),
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
        consecutive_failures = 0
        while not self._stop.is_set():
            try:
                processed_count = self.service.scan_once()
                if consecutive_failures:
                    self.service.record_watcher_recovery()
                consecutive_failures = 0
                self.service.record_watcher_health(
                    status="HEALTHY",
                    consecutive_failures=0,
                    processed_count=processed_count,
                )
            except Exception as exc:
                # The watcher is a long-lived auxiliary process. A bad file, a
                # transient OneDrive state, or a database contention must not kill it.
                LOGGER.exception("File watcher cycle failed; retrying on next poll")
                consecutive_failures += 1
                try:
                    self.service.record_watcher_health(
                        status="DEGRADED",
                        consecutive_failures=consecutive_failures,
                        error=exc,
                    )
                except Exception:
                    LOGGER.exception("Could not persist file watcher health state")
                try:
                    self.service.record_watcher_failure(exc, consecutive_failures)
                except Exception:
                    LOGGER.exception("Could not record file watcher health notification")
            self._stop.wait(self.interval_seconds)
#endfile
