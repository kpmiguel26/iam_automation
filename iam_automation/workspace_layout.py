"""
File: iam_automation/workspace_layout.py
Purpose: Provides the workspace layout component of IAM Automation.
Responsibilities: Exposes or coordinates: ensure_sharepoint_structure.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

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
    "generated_templates",
    "exports",
    "manifests",
    "bug_reports/open",
    "bug_reports/in_progress",
    "bug_reports/resolved",
    "bug_reports/closed",
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
#endfile
