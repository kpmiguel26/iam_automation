from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import toml as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "sample_config.toml"
WEB_PATH_PREFIXES = ("http://", "https://", "sharepoint://", "ms-excel:", "odopen://")


@dataclass(frozen=True)
class PathResource:
    key: str
    label: str
    expected_type: str
    required: bool
    extension: str | None = None


RESOURCES = [
    PathResource("published_access_db_path", "Published Access database", "file", True, ".accdb"),
    PathResource("sharepoint_root_path", "SharePoint library root", "folder", True),
    PathResource("workspace_path", "Local workspace", "folder", True),
    PathResource("backup_folder_path", "Backup folder", "folder", True),
    PathResource("audit_folder_path", "Audit folder", "folder", True),
    PathResource("generated_templates_path", "Generated templates folder", "folder", False),
]

ENV_KEYS = {
    "published_access_db_path": "IAM_PUBLISHED_ACCESS_DB_PATH",
    "sharepoint_root_path": "IAM_SHAREPOINT_ROOT_PATH",
    "workspace_path": "IAM_WORKSPACE_PATH",
    "backup_folder_path": "IAM_BACKUP_FOLDER_PATH",
    "audit_folder_path": "IAM_AUDIT_FOLDER_PATH",
    "generated_templates_path": "IAM_GENERATED_TEMPLATES_PATH",
    "approved_users_path": "IAM_APPROVED_USERS_PATH",
}


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _config_defaults(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, str]:
    data = _load_toml(config_path)
    paths = data.get("paths", {}) if isinstance(data.get("paths"), dict) else {}
    security = data.get("security", {}) if isinstance(data.get("security"), dict) else {}
    return {
        "published_access_db_path": str(paths.get("published_access_db_path", "") or ""),
        "sharepoint_root_path": str(paths.get("sharepoint_root_path", "") or ""),
        "workspace_path": str(paths.get("workspace_path", "") or ""),
        "backup_folder_path": str(paths.get("backup_folder_path", "") or ""),
        "audit_folder_path": str(paths.get("audit_folder_path", "") or ""),
        "generated_templates_path": str(paths.get("generated_templates_path", "") or ""),
        "approved_users_path": str(security.get("approved_users_path", "") or ""),
    }


def _env_defaults() -> dict[str, str]:
    return {key: str(os.environ.get(env_key, "") or "").strip() for key, env_key in ENV_KEYS.items()}


def _is_web_path(raw_path: str) -> bool:
    normalized = raw_path.strip().lower()
    return normalized.startswith(WEB_PATH_PREFIXES) or "sharepoint.com" in normalized


def looks_like_onedrive_path(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/").lower()
    return "/onedrive" in normalized or "onedrive -" in normalized


def resolve_path_settings(
    overrides: dict[str, Any] | None = None,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, str]:
    config_defaults = _config_defaults(config_path)
    env_defaults = _env_defaults()
    provided = {
        key: str((overrides or {}).get(key, "") or "").strip()
        for key in {resource.key for resource in RESOURCES} | {"approved_users_path"}
        if str((overrides or {}).get(key, "") or "").strip()
    }
    resolved: dict[str, str] = {}
    for key in {resource.key for resource in RESOURCES} | {"approved_users_path"}:
        resolved[key] = provided.get(key) or env_defaults.get(key) or config_defaults.get(key) or ""
    return resolved


def validation_payload(
    values: dict[str, Any] | None = None,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    resolved = resolve_path_settings(values, config_path=config_path)
    resources = []
    for resource in RESOURCES:
        raw_path = str(resolved.get(resource.key, "") or "").strip()
        status = "ok"
        message = f"{resource.label} is ready."

        if not raw_path:
            status = "empty"
            message = f"{resource.label} is not configured."
        elif _is_web_path(raw_path):
            status = "web_path"
            message = (
                f"{resource.label} must be a local OneDrive-synced path, not a SharePoint or web link: {raw_path}"
            )
        else:
            path = Path(raw_path).expanduser()
            if not path.exists():
                status = "missing"
                message = f"{resource.label} was not found: {raw_path}"
            elif resource.expected_type == "file" and not path.is_file():
                status = "invalid_type"
                message = f"{resource.label} must be a file: {raw_path}"
            elif resource.expected_type == "folder" and not path.is_dir():
                status = "invalid_type"
                message = f"{resource.label} must be a folder: {raw_path}"
            elif resource.extension and path.suffix.lower() != resource.extension:
                status = "invalid_extension"
                message = f"{resource.label} must be a {resource.extension} file: {raw_path}"
            elif resource.key in {"published_access_db_path", "sharepoint_root_path"} and not looks_like_onedrive_path(raw_path):
                status = "outside_onedrive"
                message = (
                    f"{resource.label} must be inside the local OneDrive sync folder, not a standalone local path: {raw_path}"
                )
            elif resource.key == "workspace_path" and looks_like_onedrive_path(raw_path):
                status = "workspace_in_onedrive"
                message = f"{resource.label} must be outside the OneDrive sync folder: {raw_path}"

        if not resource.required and status in {"empty", "missing"}:
            message = f"{resource.label} is optional and not configured."

        resources.append(
            {
                "key": resource.key,
                "label": resource.label,
                "path": raw_path,
                "required": resource.required,
                "status": status,
                "message": message,
            }
        )

    ok = all(
        item["status"] == "ok" or (not item["required"] and item["status"] in {"empty", "missing"})
        for item in resources
    )
    return {"ok": ok, "paths": resolved, "resources": resources}
