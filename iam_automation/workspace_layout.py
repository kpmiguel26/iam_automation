from __future__ import annotations

from pathlib import Path


SHAREPOINT_FOLDERS = (
    "database",
    "database/snapshots",
    "requests/pending",
    "requests/imported",
    "requests/approved",
    "requests/rejected",
    "requests/applied",
    "requests/failed",
    "requests/quarantine",
    "audit",
    "backups",
    "templates",
    "exports",
    "manifests",
)


def ensure_sharepoint_structure(root: Path) -> tuple[Path, ...]:
    """Create only folders; database files are never created or replaced here."""
    created: list[Path] = []
    for relative_path in SHAREPOINT_FOLDERS:
        folder = root / relative_path
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)
    return tuple(created)
