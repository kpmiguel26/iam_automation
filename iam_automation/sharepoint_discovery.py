"""
File: iam_automation/sharepoint_discovery.py
Purpose: Provides the sharepoint discovery component of IAM Automation.
Responsibilities: Exposes or coordinates: DiscoveryCandidate, _candidate_for, common_search_roots, discover_candidates.
Dependencies: config
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import looks_like_onedrive_path


EXPECTED_MARKERS = ("database", "requests", "audit", "backups", "templates", "generated_templates", "exports")


@dataclass(frozen=True)
class DiscoveryCandidate:
    path: Path
    score: int
    access_databases: tuple[Path, ...]
    matched_markers: tuple[str, ...]
    runtime_databases: tuple[Path, ...] = ()

    @property
    def is_usable(self) -> bool:
        return self.path.is_dir() and len(self.runtime_databases) == 1 and bool(self.matched_markers)


def _candidate_for(path: Path) -> DiscoveryCandidate | None:
    if not path.is_dir() or not looks_like_onedrive_path(str(path)):
        return None
    try:
        databases = tuple(sorted(item for item in (path / "database").glob("*.accdb") if item.is_file())) or tuple(sorted(item for item in path.glob("*.accdb") if item.is_file()))
        runtime_databases = tuple(sorted(item for item in (path / "database" / "snapshots").glob("*.sqlite") if item.is_file())) or tuple(sorted(item for item in path.glob("*.sqlite") if item.is_file()))
        markers = tuple(marker for marker in EXPECTED_MARKERS if (path / marker).is_dir())
    except OSError:
        return None
    if not markers:
        return None
    score = len(markers) * 10 + (50 if len(runtime_databases) == 1 else 0)
    return DiscoveryCandidate(path=path, score=score, access_databases=databases, matched_markers=markers, runtime_databases=runtime_databases)


def common_search_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for key in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        raw = os.environ.get(key, "").strip()
        if raw:
            roots.append(Path(raw).expanduser())
    home = Path.home()
    roots.extend(home.glob("OneDrive*"))
    if os.sys.platform == "darwin":
        roots.extend((home / "Library" / "CloudStorage").glob("OneDrive-*"))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.expanduser().resolve(strict=False)).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root.expanduser())
    return tuple(unique)


def discover_candidates(search_roots: tuple[Path, ...] | None = None, *, max_depth: int = 4) -> tuple[DiscoveryCandidate, ...]:
    candidates: dict[str, DiscoveryCandidate] = {}
    for search_root in search_roots or common_search_roots():
        if not search_root.is_dir():
            continue
        queue: list[tuple[Path, int]] = [(search_root, 0)]
        while queue:
            current, depth = queue.pop(0)
            candidate = _candidate_for(current)
            if candidate:
                key = str(current.resolve(strict=False)).lower()
                existing = candidates.get(key)
                if existing is None or candidate.score > existing.score:
                    candidates[key] = candidate
            if depth >= max_depth:
                continue
            try:
                children = sorted(item for item in current.iterdir() if item.is_dir() and not item.name.startswith("."))
            except OSError:
                continue
            queue.extend((child, depth + 1) for child in children)
    return tuple(sorted(candidates.values(), key=lambda item: (-item.score, str(item.path).lower())))
#endfile
