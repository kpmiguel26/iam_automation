"""
File: iam_automation/settings_store.py
Purpose: Provides the settings store component of IAM Automation.
Responsibilities: Exposes or coordinates: user_settings_path, load_user_settings, save_user_settings.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import toml as tomllib  # type: ignore[no-redef]


def user_settings_path() -> Path:
    """Return a per-user settings location outside the repository and SharePoint."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "IAMAutomation" / "settings.toml"


def load_user_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or user_settings_path()
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as handle:
            # Use ``loads`` with decoded text because the Python < 3.11
            # ``toml`` fallback does not consistently accept binary handles.
            data = tomllib.loads(handle.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        # A partially written settings file must never prevent the launcher
        # from starting. Preserve it for diagnostics, then recover cleanly.
        try:
            backup = settings_path.with_name(
                f"{settings_path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            )
            settings_path.replace(backup)
        except OSError:
            pass
        return {}
    return data if isinstance(data, dict) else {}


def save_user_settings(values: dict[str, Any], path: Path | None = None) -> Path:
    """Persist only local runtime settings using a small deterministic TOML writer."""
    settings_path = path or user_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    paths = values.get("paths", {}) if isinstance(values.get("paths"), dict) else {}
    security = values.get("security", {}) if isinstance(values.get("security"), dict) else {}
    lines = ["[paths]"]
    for key, value in paths.items():
        if value:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    if security:
        lines.extend(["", "[security]"])
        for key, value in security.items():
            if value:
                escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
    temporary = settings_path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(settings_path)
    return settings_path
#endfile
