"""
File: iam_automation/application/file_watch_service.py
Purpose: Implements the application service for file watch service workflows.
Responsibilities: Exposes or coordinates: FileObservation, watcher_health_path, load_watcher_health, FileWatchService, FileWatcher.
Dependencies: sqlalchemy, infrastructure, change_request, identity
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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import AppUserModel, FileObservationModel, UserRoleModel, orm_session
from ..change_request import load_request_file
from .notification_service import NotificationService
from .workspace_refresh_service import WORKSPACE_IO_LOCK, local_runtime_checksum_path, record_local_runtime_checksum
from .ingestion.common import read_stable_bytes


LOGGER = logging.getLogger(__name__)
EXPECTED_WATCHER_ERRORS = (OSError, PermissionError, ValueError, RuntimeError)


@dataclass(frozen=True)
class FileObservation:
    path: str
    file_kind: str
    signature: str


def watcher_health_path(database_path: Path) -> Path:
    """Return the local, non-published watcher health sidecar path."""
    return database_path.with_name(database_path.name + ".watcher-health.json")


def watcher_manifest_path(database_path: Path) -> Path:
    """Return the local discovery manifest; it is deliberately not SQLite data."""
    return database_path.with_name(database_path.name + ".watcher-manifest.json")


def load_watcher_manifest(database_path: Path) -> dict[str, object]:
    path = watcher_manifest_path(database_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def save_watcher_manifest(database_path: Path, observations: list[FileObservation]) -> None:
    previous = load_watcher_manifest(database_path)
    previous_items = previous.get("observations", {})
    items = dict(previous_items) if isinstance(previous_items, dict) else {}
    active_paths = {item.path for item in observations}
    for item in observations:
        old = items.get(item.path, {})
        old = old if isinstance(old, dict) else {}
        items[item.path] = {
            "path": item.path,
            "source_system": item.file_kind,
            "source_file": Path(item.path).name,
            "source_checksum": item.signature,
            "status": old.get("status", "DETECTED"),
            "detected_at_utc": old.get("detected_at_utc") or datetime.now(timezone.utc).isoformat(),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    # A deleted OneDrive file should disappear from the active discovery list.
    items = {path: item for path, item in items.items() if path in active_paths}
    path = watcher_manifest_path(database_path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps({"version": 1, "observations": items}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_watcher_health(database_path: Path) -> dict[str, object]:
    """Read the last watcher state without making health part of SQLite data."""
    path = watcher_health_path(database_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


class FileWatchService:
    """Detect shared changes without writing source reports to SQLite.

    The watcher writes only its discovery manifest and health sidecars. Source
    workbooks and AccessNow reports are staged when a human starts an import;
    promotion into canonical workers remains an explicit administrative action.
    """

    def __init__(self, database_path: Path, sharepoint_root: Path):
        self.database_path = database_path
        self.sharepoint_root = sharepoint_root
        # File and ingestion notifications belong to this workstation. The
        # only global notification is emitted explicitly by database publish.
        self.notifications = NotificationService(database_path)

    def start(self, interval_seconds: float = 120.0) -> "FileWatcher":
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
        # Use a process-unique temporary name. A fixed ``.tmp`` collides when
        # two launcher processes briefly run the watcher at the same time.
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        last_error = None
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError as exc:
                last_error = exc
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        if last_error and temporary.exists():
            raise last_error

    def scan_once(self) -> int:
        # Discovery is intentionally filesystem-only. Importing a report is an
        # explicit user action and is the only operation allowed to populate
        # SQLite with source rows and star facts.
        with WORKSPACE_IO_LOCK:
            observations = self._discover_files()
            save_watcher_manifest(self.database_path, observations)
            if not observations:  # pragma: no cover - retained for old traces
                return 0
            # The watcher itself writes observations to the local runtime and
            # notifications to the local file store. Preserve a genuine user edit, but advance the
            # sidecar after an automatic scan that started from a clean state.
            sidecar = local_runtime_checksum_path(self.database_path)
            watcher_started_clean = sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() == hashlib.sha256(self.database_path.read_bytes()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            changed = self._changed_observations(observations)
            changed.sort(key=self._observation_priority)
            successful_observations: set[str] = set()
            review_requests: set[str] = set()
            for observation in changed:
                try:
                    if observation.file_kind == "APPROVED_IMPORT":
                        self._sync_approved_import(Path(observation.path))
                        # The approval JSON is only a shared signal. It must not
                        # create a generic file alert or imply that canonical
                        # employees were already updated.
                        review_requests.add(observation.path)
                    else:
                        # Source files are discovery-only here. The explicit
                        # Source Updates import action owns parsing, staging,
                        # rules and SQLite writes.
                        LOGGER.info("Source file discovered; waiting for explicit import: %s", observation.path)
                    successful_observations.add(observation.path)
                except EXPECTED_WATCHER_ERRORS as exc:
                    # Approval signals may be temporarily unavailable. Source
                    # report discovery itself never writes source data.
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
            pending_notifications: list[tuple[str, FileObservation]] = []
            with orm_session(self.database_path) as session:
                for observation in changed:
                    if observation.path not in successful_observations:
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
                            pending_notifications.append((username, observation))
            for username, observation in pending_notifications:
                notification = self._notification(username, observation)
                self.notifications.create(
                    username,
                    notification["notification_type"],
                    notification["title"],
                    notification["message"],
                    severity=notification["severity"],
                    target_route=notification["target_route"],
                    entity_type=notification["entity_type"],
                    entity_id=notification["entity_id"],
                    notification_id=notification["notification_id"],
                )
            # The explicit Source Updates import action owns ingestion and the
            # BEFORE/AFTER configurable-rule boundary. The watcher only
            # coordinates discovery notifications here.
            if watcher_started_clean:
                record_local_runtime_checksum(self.database_path)
            return len(successful_observations)

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
        for username in admins:
            self.notifications.create(
                username,
                "INGESTION_ERROR",
                f"{observation.file_kind.replace('_', ' ').title()} {'unexpected failure' if unexpected else 'ingestion failed'}",
                f"The workbook could not be staged and will be retried: {type(error).__name__}: {error}",
                severity="ERROR",
                entity_type="file",
                entity_id=observation.path,
                target_route="/admin/imports",
                notification_id=hashlib.sha256(f"{username}:{observation.path}:{observation.signature}:failure".encode()).hexdigest(),
            )

    def _sync_approved_import(self, path: Path) -> None:
        """Register an approved source file for individual review.

        Approval JSON is a shared signal, not permission to bulk-write every
        row into the local canonical database. Promotion happens one employee
        at a time from Source Updates, where matching, history, and business
        rules are visible to the reviewer.
        """
        request = load_request_file(path)
        if request.operation_type not in {"IMPORT_ROSTER_LOCK", "IMPORT_MASTER_ROSTER", "IMPORT_RSR_SUPPLIER_DETAILS", "IMPORT_ACCESSNOW"}:
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
        """Find pending work across legacy folders and workspace operations.

        DEPRECATED (migration in progress): the four source-report scans below
        overlap with runtime v2's template-configured discovery and recognition.
        Keep them active until v2 import and source-by-source cutover are ready;
        the remaining request, configuration, snapshot and approval scans are
        outside the parallel engine's scope.
        """
        roots = (
            (self.sharepoint_root / "requests" / "pending", "PENDING_REQUEST"),
            (self.sharepoint_root / "config", "CONFIGURATION"),
            (self.sharepoint_root / "database" / "snapshots" / "identity_discoveries", "IDENTITY_DISCOVERY"),
            (self.sharepoint_root / "database" / "snapshots", "PUBLISHED_RUNTIME"),
            (self.sharepoint_root / "rosterlocks", "ROSTER_LOCK"),
            (self.sharepoint_root / "master_roster", "MASTER_ROSTER"),
            (self.sharepoint_root / "rsrsuplierworkerdetails", "RSR_SUPPLIER_WORKER_DETAILS"),
            (self.sharepoint_root / "acessnow", "ACCESSNOW"),
            (self.sharepoint_root / "requests" / "approved", "APPROVED_IMPORT"),
        )
        observations: list[FileObservation] = []
        for root, kind in roots:
            if not root.is_dir():
                continue
            patterns = ("*.json", "*.toml") if kind == "CONFIGURATION" else (("iam_runtime.sqlite",) if kind == "PUBLISHED_RUNTIME" else (("*.xlsx", "*.csv") if kind == "ACCESSNOW" else (("*.xlsx",) if kind in {"ROSTER_LOCK", "MASTER_ROSTER", "RSR_SUPPLIER_WORKER_DETAILS"} else ("*.json",))))
            for pattern in patterns:
                for path in root.glob(pattern):
                    if path.is_file() and not path.name.startswith("."):
                        # Metadata-only signatures miss in-place edits that
                        # preserve size and timestamp resolution. The content
                        # checksum is also the identity used by ingestion,
                        # so the watcher and source pipeline now agree.
                        try:
                            signature = hashlib.sha256(read_stable_bytes(path)).hexdigest()
                        except OSError as exc:
                            # OneDrive may hold a placeholder while it finishes
                            # downloading or uploading. Do not let one file
                            # block the remaining source folders; the next
                            # watcher cycle will retry it.
                            LOGGER.warning("Skipping temporarily unavailable source file; will retry: %s (%s)", path, exc)
                            continue
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
        for username in admins:
            notification_id = hashlib.sha256(f"watcher-cycle:{username}:{fingerprint}".encode("utf-8")).hexdigest()
            existing = self.notifications.local_store.get(username, notification_id)
            if existing and str(existing.get("status")) in {"RESOLVED", "EXPIRED"}:
                self.notifications.local_store.set_status(username, notification_id, "UNREAD")
            self.notifications.create(
                username,
                "WATCHER_CYCLE_FAILURE",
                "File watcher is repeatedly failing",
                f"The watcher has failed {consecutive_failures} consecutive cycle(s) and will keep retrying: {type(error).__name__}: {error}",
                severity="CRITICAL",
                entity_type="file_watcher",
                entity_id="iam-file-watcher",
                target_route="/admin/imports",
                notification_id=notification_id,
            )

    def record_watcher_recovery(self) -> None:
        """Resolve open watcher failure notifications after a healthy cycle."""
        for item in self.notifications.local_store.list_all(notification_type="WATCHER_CYCLE_FAILURE"):
            if str(item.get("status")) in {"UNREAD", "READ"}:
                self.notifications.local_store.set_status(
                    str(item.get("recipient_username", "")),
                    str(item.get("notification_id", "")),
                    "RESOLVED",
                )

    @staticmethod
    def _notification(username: str, observation: FileObservation) -> dict[str, str]:
        labels = {
            "PENDING_REQUEST": ("New request file detected", "A new JSON request is waiting in the pending folder."),
            "CONFIGURATION": ("Configuration file detected", "A configuration file changed and is ready for review."),
            "IDENTITY_DISCOVERY": ("Identity discovery updated", "A workstation identity record is available for administrative review."),
            "PUBLISHED_RUNTIME": ("New database snapshot published", "A new runtime SQLite snapshot is available. Refresh this workstation when you are not editing a form."),
            "ROSTER_LOCK": ("Roster Lock discovered", "A vendor Roster Lock workbook was found and is ready for explicit import."),
            "MASTER_ROSTER": ("Master Roster discovered", "A Master Roster workbook was found and is ready for explicit import."),
            "RSR_SUPPLIER_WORKER_DETAILS": ("RSR worker details discovered", "Supplier worker details were found and are ready for explicit import."),
            "ACCESSNOW": ("AccessNow reports discovered", "Active and termination reports were found and are ready for explicit import."),
            "APPROVED_IMPORT": ("Employee updates ready", "Approved source records are ready for individual matching and review. No employee was created automatically."),
        }
        title, message = labels[observation.file_kind]
        return {
            "notification_id": hashlib.sha256(f"{username}:{observation.path}:{observation.signature}".encode()).hexdigest(),
            "notification_type": "FILE_DETECTED",
            "severity": "WARNING" if observation.file_kind != "CONFIGURATION" else "INFO",
            "title": title,
            "message": f"{message} File: {Path(observation.path).name}",
            "entity_type": "file",
            "entity_id": observation.path,
            "target_route": ("/admin/approvals" if observation.file_kind == "PENDING_REQUEST" else "/dashboard" if observation.file_kind == "PUBLISHED_RUNTIME" else "/employees/source-updates" if observation.file_kind in {"APPROVED_IMPORT", "ACCESSNOW"} else "/admin/imports" if observation.file_kind in {"ROSTER_LOCK", "MASTER_ROSTER", "RSR_SUPPLIER_WORKER_DETAILS"} else "/admin"),
        }


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
                self.service.record_watcher_health(status="SCANNING", consecutive_failures=consecutive_failures)
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
