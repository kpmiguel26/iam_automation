from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from . import config
from .database import initialize_runtime_database
from .identity import CurrentUser, auto_approve_current_user_for_development, load_approved_users_from_sqlite, validate_current_user, validate_current_user_from_sqlite
from .runtime_sync import find_published_access_db, find_published_runtime_db, project_runtime_path, publish_runtime_snapshot, sync_runtime_snapshot
from .settings_store import load_user_settings, save_user_settings, user_settings_path
from .sharepoint_discovery import DiscoveryCandidate, discover_candidates
from .workspace_layout import ensure_sharepoint_structure


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
    published_access_db_path: Path
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
            "published_access_db_path": str(self.published_access_db_path),
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
    access_database = find_published_access_db(root) or root / "database" / "iam_automation.accdb"
    runtime_database = find_published_runtime_db(root) or root / "database" / "snapshots" / "iam_runtime.sqlite"
    return StartupSettings(
        sharepoint_root_path=root,
        published_access_db_path=access_database,
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
        preferred = explicit or str(saved.get("sharepoint_root_path", "") or configured).strip()
        if preferred and not config._is_web_path(preferred):
            root = Path(preferred).expanduser()
            if root.is_dir():
                settings = settings_for_root(root, config_path=self.config_path, settings_path=self.settings_path)
                if settings:
                    self.candidates = (DiscoveryCandidate(root, 1000, (settings.published_access_db_path,), tuple(item for item in ("database", "requests", "audit", "backups") if (root / item).is_dir())),)
                    self.state = StartupState.CANDIDATE_FOUND
                    self.settings = settings
                    return self._result(True, "SharePoint path found from configuration.")
        self.candidates = discover_candidates()
        if not self.candidates:
            self.state = StartupState.NOT_FOUND
            return self._result(False, "No local OneDrive-synchronized SharePoint folder with both databases was found.")
        if len(self.candidates) > 1:
            self.state = StartupState.MULTIPLE_CANDIDATES
            return self._result(False, "Multiple SharePoint candidates were found. Select one to continue.")
        self.settings = settings_for_root(self.candidates[0].path, config_path=self.config_path, settings_path=self.settings_path)
        self.state = StartupState.CANDIDATE_FOUND if self.settings else StartupState.INVALID_PATH
        return self._result(bool(self.settings), "SharePoint candidate found." if self.settings else "The selected candidate must contain both the Access database and runtime SQLite database.")

    def select_sharepoint_path(self, path: Path) -> PreflightResult:
        self.settings = settings_for_root(path, config_path=self.config_path, settings_path=self.settings_path)
        self.candidates = ()
        self.state = StartupState.CANDIDATE_FOUND if self.settings else StartupState.INVALID_PATH
        return self._result(bool(self.settings), "Selected SharePoint path is ready for validation." if self.settings else "Selected path must contain exactly one Access database and one runtime SQLite database.")

    def validate_environment(self) -> PreflightResult:
        if not self.settings:
            self.state = StartupState.INVALID_PATH
            return self._result(False, "A valid SharePoint path must be selected before validation.")
        self.state = StartupState.VALIDATING
        if not config.looks_like_onedrive_path(str(self.settings.workspace_path)):
            self.settings.workspace_path.mkdir(parents=True, exist_ok=True)
        ensure_sharepoint_structure(self.settings.sharepoint_root_path)
        payload = config.validation_payload(self.settings.as_overrides(), config_path=self.config_path)
        resources = list(payload["resources"])
        if not self.settings.published_access_db_path.stat().st_mode & 0o444:
            resources.append({"key": "access_readability", "label": "Access database readability", "path": str(self.settings.published_access_db_path), "required": True, "status": "unreadable", "message": "Access database is not readable by the current process."})
        ok = bool(payload["ok"]) and all(item["status"] == "ok" for item in resources if item.get("required"))
        if ok:
            try:
                snapshot = sync_runtime_snapshot(self.settings.published_runtime_db_path, self.settings.local_runtime_db_path)
                initialize_runtime_database(snapshot.local_path)
                resources.append({
                    "key": "runtime_sync",
                    "label": "Local runtime SQLite synchronization",
                    "path": str(snapshot.local_path),
                    "required": True,
                    "status": "ok",
                    "message": f"Published SQLite validated and copied locally. SHA-256: {snapshot.checksum[:16]}...",
                })
            except Exception as exc:
                resources.append({"key": "runtime_sync", "label": "Local runtime SQLite synchronization", "path": str(self.settings.local_runtime_db_path), "required": True, "status": "invalid", "message": str(exc)})
                ok = False
        self.state = StartupState.READY if ok else (StartupState.ACCESS_UNAVAILABLE if self.settings.published_access_db_path.exists() is False else StartupState.INVALID_PATH)
        if ok:
            save_user_settings({"paths": self.settings.as_overrides()}, self.settings_path)
        self.result = PreflightResult(self.state, ok, "Environment is ready." if ok else "Environment validation failed.", self.settings, tuple(resources), self.candidates)
        return self.result

    def continue_to_login(self) -> CurrentUser:
        if self.state != StartupState.READY or not self.result or not self.result.ok:
            raise RuntimeError("SharePoint preflight must pass before login.")
        approved_path = self.settings.approved_users_path if self.settings else None
        try:
            runtime_users = load_approved_users_from_sqlite(self.settings.local_runtime_db_path) if self.settings else {}
            if runtime_users:
                try:
                    user = validate_current_user_from_sqlite(self.settings.local_runtime_db_path)
                except PermissionError:
                    if not config.dev_auto_approve_users_enabled():
                        raise
                    user = auto_approve_current_user_for_development(self.settings.local_runtime_db_path, config.dev_default_role())
                    publish_runtime_snapshot(
                        self.settings.local_runtime_db_path,
                        self.settings.published_runtime_db_path,
                        actor=f"development-auto-approval:{user.username}",
                    )
            elif config.dev_auto_approve_users_enabled():
                user = auto_approve_current_user_for_development(self.settings.local_runtime_db_path, config.dev_default_role())
                publish_runtime_snapshot(
                    self.settings.local_runtime_db_path,
                    self.settings.published_runtime_db_path,
                    actor=f"development-auto-approval:{user.username}",
                )
            elif approved_path:
                user = validate_current_user(approved_path)
            else:
                raise PermissionError("No approved Windows identities are configured.")
        except PermissionError:
            self.state = StartupState.UNAUTHORIZED_USER
            raise
        self.result = PreflightResult(self.state, True, "Environment and user are ready.", self.settings, self.result.resources, self.candidates, user)
        return user

    def retry(self) -> PreflightResult:
        self.settings = None
        return self.discover_sharepoint()

    def _result(self, ok: bool, message: str) -> PreflightResult:
        self.result = PreflightResult(self.state, ok, message, self.settings, (), self.candidates)
        return self.result
