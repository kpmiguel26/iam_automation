"""
File: iam_automation/startup.py
Purpose: Provides the startup component of IAM Automation.
Responsibilities: Exposes or coordinates: StartupState, StartupSettings, PreflightResult, _default_workspace, _path_from, settings_for_root, ….
Dependencies: application, database, identity, identity_discovery, runtime_sync
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import os
import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from . import config
from .application.audit_service import record_audit
from .database import initialize_runtime_database
from .application.publication_state import mark_publication_pending
from .application.user_service import UserService
from .application.workspace_refresh_service import record_published_source_checksum
from .identity import CurrentUser
from .identity import computer_name, windows_username
from .identity_discovery import record_windows_traceability, traceability_path
from .runtime_sync import RuntimeDatabaseError, find_published_runtime_db, project_runtime_path, sync_runtime_snapshot
from .settings_store import load_user_settings, save_user_settings, user_settings_path
from .sharepoint_discovery import DiscoveryCandidate, discover_candidates
from .workspace_layout import ensure_sharepoint_structure


LOGGER = logging.getLogger(__name__)


class StartupState(str, Enum):
    DISCOVERING = "DISCOVERING"
    CANDIDATE_FOUND = "CANDIDATE_FOUND"
    VALIDATING = "VALIDATING"
    READY = "READY"
    NOT_FOUND = "NOT_FOUND"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    INVALID_PATH = "INVALID_PATH"
    ACCESS_UNAVAILABLE = "ACCESS_UNAVAILABLE"
    UNAUTHORIZED_USER = "UNAUTHORIZED_USER"


@dataclass(frozen=True)
class StartupSettings:
    sharepoint_root_path: Path
    # Retained in its historical position so older integrations that create
    # this dataclass positionally continue to work. It is not validated.
    published_access_db_path: Path | None
    published_runtime_db_path: Path
    local_runtime_db_path: Path
    workspace_path: Path
    backup_folder_path: Path
    audit_folder_path: Path
    generated_templates_path: Path | None = None
    approved_users_path: Path | None = None

    def as_overrides(self) -> dict[str, str]:
        return {
            "sharepoint_root_path": str(self.sharepoint_root_path),
            "published_access_db_path": str(self.published_access_db_path or ""),
            "published_runtime_db_path": str(self.published_runtime_db_path),
            "workspace_path": str(self.workspace_path),
            "backup_folder_path": str(self.backup_folder_path),
            "audit_folder_path": str(self.audit_folder_path),
            "generated_templates_path": str(self.generated_templates_path or ""),
            "approved_users_path": str(self.approved_users_path or ""),
        }


@dataclass(frozen=True)
class PreflightResult:
    state: StartupState
    ok: bool
    message: str
    settings: StartupSettings | None = None
    resources: tuple[dict[str, Any], ...] = ()
    candidates: tuple[DiscoveryCandidate, ...] = ()
    current_user: CurrentUser | None = None


def _default_workspace() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "IAMAutomation" / "workspace"
    if os.sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "IAMAutomation" / "workspace"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "IAMAutomation" / "workspace"


def _path_from(data: dict[str, Any], key: str, *, base: Path | None = None) -> Path | None:
    raw = str(data.get(key, "") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return (base / path) if base and not path.is_absolute() else path


def settings_for_root(root: Path, *, config_path: Path | None = None, settings_path: Path | None = None) -> StartupSettings | None:
    root = root.expanduser()
    if not root.is_dir():
        return None
    config_values = config.resolve_path_settings(config_path=config_path or config.DEFAULT_CONFIG_PATH)
    user_values = load_user_settings(settings_path)
    user_paths = user_values.get("paths", {}) if isinstance(user_values.get("paths"), dict) else {}
    workspace = _path_from(user_paths, "workspace_path") or _path_from(config_values, "workspace_path") or _default_workspace()
    config_reference = config_path or config.DEFAULT_CONFIG_PATH
    config_base = config_reference.parents[1] if config_reference == config.DEFAULT_CONFIG_PATH else config_reference.parent
    approved = _path_from(user_paths, "approved_users_path") or _path_from(config_values, "approved_users_path", base=config_base)
    runtime_database = find_published_runtime_db(root) or root / "database" / "snapshots" / "iam_runtime.sqlite"
    return StartupSettings(
        sharepoint_root_path=root,
        published_access_db_path=None,
        published_runtime_db_path=runtime_database,
        local_runtime_db_path=project_runtime_path(),
        workspace_path=workspace,
        backup_folder_path=root / "backups",
        audit_folder_path=root / "audit",
        generated_templates_path=root / "generated_templates",
        approved_users_path=approved,
    )


class StartupController:
    def __init__(self, *, config_path: Path | None = None, settings_path: Path | None = None):
        self.config_path = config_path or config.DEFAULT_CONFIG_PATH
        self.settings_path = settings_path or user_settings_path()
        self.state = StartupState.DISCOVERING
        self.candidates: tuple[DiscoveryCandidate, ...] = ()
        self.settings: StartupSettings | None = None
        self.result: PreflightResult | None = None

    def discover_sharepoint(self) -> PreflightResult:
        self.state = StartupState.DISCOVERING
        configured = config.resolve_path_settings(config_path=self.config_path).get("sharepoint_root_path", "")
        saved = load_user_settings(self.settings_path).get("paths", {})
        saved = saved if isinstance(saved, dict) else {}
        explicit = os.environ.get("IAM_SHAREPOINT_ROOT_PATH", "").strip()
        saved_root = str(saved.get("sharepoint_root_path", "") or "").strip()
        preferred = explicit or saved_root or str(configured or "").strip()
        if preferred and not config._is_web_path(preferred):
            root = Path(preferred).expanduser()
            recreated = False
            if (
                not root.is_dir()
                and (explicit or saved_root)
                and root.parent.is_dir()
                and config.looks_like_onedrive_path(str(root))
            ):
                try:
                    root.mkdir(parents=True, exist_ok=True)
                    recreated = True
                except OSError as exc:
                    self.state = StartupState.INVALID_PATH
                    return self._result(False, f"The configured OneDrive folder could not be recreated: {exc}")
            if root.is_dir():
                settings = settings_for_root(root, config_path=self.config_path, settings_path=self.settings_path)
                if settings:
                    self.candidates = (DiscoveryCandidate(root, 1000, tuple(), tuple(item for item in ("database", "requests", "audit", "backups", "reports") if (root / item).is_dir()), (settings.published_runtime_db_path,)),)
                    self.state = StartupState.CANDIDATE_FOUND
                    self.settings = settings
                    message = "SharePoint folder was recreated from saved settings." if recreated else "SharePoint path found from configuration."
                    return self._result(True, message)
        self.candidates = discover_candidates()
        if not self.candidates:
            self.state = StartupState.NOT_FOUND
            return self._result(False, "No local OneDrive-synchronized SharePoint folder with a runtime SQLite database was found.")
        if len(self.candidates) > 1:
            self.state = StartupState.MULTIPLE_CANDIDATES
            return self._result(False, "Multiple SharePoint candidates were found. Select one to continue.")
        self.settings = settings_for_root(self.candidates[0].path, config_path=self.config_path, settings_path=self.settings_path)
        self.state = StartupState.CANDIDATE_FOUND if self.settings else StartupState.INVALID_PATH
        return self._result(bool(self.settings), "SharePoint candidate found." if self.settings else "The selected candidate must contain a runtime SQLite database.")

    def select_sharepoint_path(self, path: Path) -> PreflightResult:
        self.settings = settings_for_root(path, config_path=self.config_path, settings_path=self.settings_path)
        self.candidates = ()
        self.state = StartupState.CANDIDATE_FOUND if self.settings else StartupState.INVALID_PATH
        return self._result(bool(self.settings), "Selected SharePoint path is ready for validation." if self.settings else "Selected path must contain a runtime SQLite database.")

    def validate_environment(self) -> PreflightResult:
        if not self.settings:
            self.state = StartupState.INVALID_PATH
            return self._result(False, "A valid SharePoint path must be selected before validation.")
        self.state = StartupState.VALIDATING
        if not config.looks_like_onedrive_path(str(self.settings.workspace_path)):
            self.settings.workspace_path.mkdir(parents=True, exist_ok=True)
        created_folders = ensure_sharepoint_structure(self.settings.sharepoint_root_path)
        published_runtime_created = False
        runtime_initialization_error = ""
        if not self.settings.published_runtime_db_path.exists():
            try:
                initialize_runtime_database(self.settings.published_runtime_db_path)
                published_runtime_created = True
            except Exception as exc:
                LOGGER.exception("Could not initialize an empty published runtime database")
                runtime_initialization_error = f"Empty published SQLite could not be initialized ({type(exc).__name__}): {exc}"
        payload = config.validation_payload(self.settings.as_overrides(), config_path=self.config_path)
        resources = list(payload["resources"])
        resources.insert(0, {
            "key": "workspace_layout",
            "label": "Workspace folders",
            "path": str(self.settings.sharepoint_root_path),
            "required": True,
            "status": "created" if created_folders else "ok",
            "message": (
                "Created missing folders: " + ", ".join(path.relative_to(self.settings.sharepoint_root_path).as_posix() for path in created_folders)
                if created_folders else "Required workspace folders are ready."
            ),
        })
        if published_runtime_created or runtime_initialization_error:
            resources.insert(1, {
                "key": "runtime_initialization",
                "label": "Published runtime SQLite initialization",
                "path": str(self.settings.published_runtime_db_path),
                "required": True,
                "status": "created" if published_runtime_created else "invalid",
                "message": (
                    "Created an empty schema without employee or history records."
                    if published_runtime_created else runtime_initialization_error
                ),
            })
        ok = bool(payload["ok"]) and not runtime_initialization_error and all(item["status"] == "ok" for item in resources if item.get("required") and item["key"] not in {"workspace_layout", "runtime_initialization"})
        if ok:
            try:
                snapshot = sync_runtime_snapshot(self.settings.published_runtime_db_path, self.settings.local_runtime_db_path)
                initialize_runtime_database(snapshot.local_path)
                record_published_source_checksum(snapshot.local_path, snapshot.checksum)
                resources.append({
                    "key": "runtime_sync",
                    "label": "Local runtime SQLite synchronization",
                    "path": str(snapshot.local_path),
                    "required": True,
                    "status": "ok",
                    "message": f"Published SQLite validated and copied locally. SHA-256: {snapshot.checksum[:16]}...",
                })
            except RuntimeDatabaseError as exc:
                resources.append({"key": "runtime_sync", "label": "Local runtime SQLite synchronization", "path": str(self.settings.local_runtime_db_path), "required": True, "status": "invalid", "message": f"SQLite validation failed: {exc}"})
                ok = False
            except OSError as exc:
                resources.append({"key": "runtime_sync", "label": "Local runtime SQLite synchronization", "path": str(self.settings.local_runtime_db_path), "required": True, "status": "invalid", "message": f"Local runtime file operation failed: {exc}"})
                ok = False
            except Exception as exc:
                LOGGER.exception("Unexpected runtime SQLite synchronization failure")
                resources.append({"key": "runtime_sync", "label": "Local runtime SQLite synchronization", "path": str(self.settings.local_runtime_db_path), "required": True, "status": "invalid", "message": f"Unexpected synchronization failure ({type(exc).__name__}): {exc}"})
                ok = False
        self.state = StartupState.READY if ok else StartupState.INVALID_PATH
        if ok:
            save_user_settings({"paths": self.settings.as_overrides()}, self.settings_path)
        self.result = PreflightResult(self.state, ok, "Environment is ready." if ok else "Environment validation failed.", self.settings, tuple(resources), self.candidates)
        return self.result

    def continue_to_login(self) -> CurrentUser:
        if self.state != StartupState.READY or not self.result or not self.result.ok:
            raise RuntimeError("SharePoint preflight must pass before login.")
        current_identity = windows_username()
        user = CurrentUser(username=current_identity, computer=computer_name(), roles=())
        if self.settings:
            record_audit(
                self.settings.audit_folder_path,
                current_identity,
                "WINDOWS_IDENTITY_RECORDED",
                "windows_identity",
                current_identity,
                computer=computer_name(),
                new_values={"computer": computer_name(), "authorization": "application_login_only"},
            )
            if sys.platform == "win32":
                try:
                    record_windows_traceability(traceability_path(self.settings.sharepoint_root_path), current_identity, computer_name())
                except OSError:
                    # SharePoint/OneDrive may temporarily remove or lock a
                    # synchronized directory while reconciling it. The local
                    # audit record above is already durable; this secondary
                    # shared observation must not block application login or
                    # first-admin setup.
                    LOGGER.warning(
                        "Windows traceability could not be written to the shared workspace; continuing startup.",
                        exc_info=True,
                    )
            if UserService(self.settings.local_runtime_db_path).ensure_initial_master_admin(current_identity):
                mark_publication_pending(
                    self.settings.local_runtime_db_path,
                    actor=current_identity,
                    reason="Initial MASTER_ADMIN password setup is required",
                )
                record_audit(
                    self.settings.audit_folder_path,
                    current_identity,
                    "INITIAL_MASTER_ADMIN_CREATED",
                    "app_user",
                    current_identity,
                    computer=computer_name(),
                    new_values={"roles": ["MASTER_ADMIN"], "status": "PASSWORD_RESET_REQUIRED"},
                )
        self.result = PreflightResult(self.state, True, "Environment and Windows identity are ready.", self.settings, self.result.resources, self.candidates, user)
        return user

    def retry(self) -> PreflightResult:
        self.settings = None
        return self.discover_sharepoint()

    def _result(self, ok: bool, message: str) -> PreflightResult:
        self.result = PreflightResult(self.state, ok, message, self.settings, (), self.candidates)
        return self.result
#endfile
