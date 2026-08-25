"""
File: iam_automation/coordinator.py
Purpose: Provides the coordinator component of IAM Automation.
Responsibilities: Exposes or coordinates: CoordinatorPaths, paths_from_settings, ensure_paths_valid, create_backup, local_working_copy, read_database_version, ….
Dependencies: audit, checksum, config, identity, lock
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from . import __version__
from .audit import append_audit_event, build_event
from .checksum import sha256_file
from .config import validation_payload
from .identity import CurrentUser
from .lock import acquire_lock, release_lock


T = TypeVar("T")


@dataclass(frozen=True)
class CoordinatorPaths:
    published_access_db_path: Path
    sharepoint_root_path: Path
    workspace_path: Path
    backup_folder_path: Path
    audit_folder_path: Path

    @property
    def lock_path(self) -> Path:
        return self.sharepoint_root_path / "_iam_automation.lock.json"

    @property
    def publication_manifest_path(self) -> Path:
        return self.sharepoint_root_path / "_iam_publication_manifest.json"


def paths_from_settings(settings: dict[str, str]) -> CoordinatorPaths:
    return CoordinatorPaths(
        published_access_db_path=Path(settings["published_access_db_path"]).expanduser(),
        sharepoint_root_path=Path(settings["sharepoint_root_path"]).expanduser(),
        workspace_path=Path(settings["workspace_path"]).expanduser(),
        backup_folder_path=Path(settings["backup_folder_path"]).expanduser(),
        audit_folder_path=Path(settings["audit_folder_path"]).expanduser(),
    )


def ensure_paths_valid(settings: dict[str, str]) -> None:
    payload = validation_payload(settings)
    if payload["ok"]:
        return
    details = "; ".join(
        item["message"] for item in payload["resources"] if item["required"] and item["status"] != "ok"
    )
    raise ValueError(f"IAM paths are not ready. {details}")


def create_backup(source: Path, backup_folder: Path) -> Path:
    backup_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_folder / f"{source.stem}_{timestamp}_{uuid.uuid4().hex[:8]}{source.suffix}"
    shutil.copy2(source, backup_path)
    return backup_path


def local_working_copy(source: Path, workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    copy_path = workspace / f"{source.stem}_working_{uuid.uuid4().hex[:8]}{source.suffix}"
    shutil.copy2(source, copy_path)
    return copy_path


def read_database_version(_: Path) -> str:
    # POC placeholder. The Access experiment will replace this with a read from app_metadata.
    return "unknown"


def run_controlled_write(
    settings: dict[str, str],
    user: CurrentUser,
    operation: str,
    callback: Callable[[Path], T],
) -> T:
    if not user.is_writer:
        raise PermissionError(f"User does not have write permissions: {user.username}")
    ensure_paths_valid(settings)
    paths = paths_from_settings(settings)
    before_checksum = sha256_file(paths.published_access_db_path)
    database_version = read_database_version(paths.published_access_db_path)
    correlation_id = str(uuid.uuid4())
    lock = acquire_lock(
        paths.lock_path,
        user=user.username,
        computer=user.computer,
        operation=operation,
        database_checksum=before_checksum,
        database_version=database_version,
        application_version=__version__,
    )
    try:
        backup_path = create_backup(paths.published_access_db_path, paths.backup_folder_path)
        working_copy = local_working_copy(paths.published_access_db_path, paths.workspace_path)
        result = callback(working_copy)
        after_checksum = sha256_file(working_copy)
        if after_checksum == before_checksum:
            outcome = "no_change"
        else:
            shutil.copy2(working_copy, paths.published_access_db_path)
            outcome = "published"
        append_audit_event(
            paths.audit_folder_path,
            build_event(
                user=user.username,
                computer=user.computer,
                action=operation,
                result=outcome,
                database_version=database_version,
                application_version=__version__,
                previous_values={"checksum": before_checksum, "backup_path": str(backup_path)},
                new_values={"checksum": after_checksum, "published_path": str(paths.published_access_db_path)},
                correlation_id=correlation_id,
            ),
        )
        return result
    except Exception as exc:
        append_audit_event(
            paths.audit_folder_path,
            build_event(
                user=user.username,
                computer=user.computer,
                action=operation,
                result="failed",
                database_version=database_version,
                application_version=__version__,
                error_details=str(exc),
                correlation_id=correlation_id,
            ),
        )
        raise
    finally:
        release_lock(paths.lock_path, lock.lock_id)
#endfile
