#!/usr/bin/env python3
"""
File: scripts/package_source.py
Purpose: Build a versioned, runnable source distribution for IAM Automation.
Responsibilities: Exposes or coordinates: project_version, git_value, is_excluded, source_files, build_manifest, create_archive, ….
Dependencies: argparse
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "dist"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "runtime_backups",
    "backups",
    "snapshots",
    "C:",
}

EXCLUDED_FIXTURE_DIRS = {
    Path("tests/fixtures/sharepoint_simulated/audit"),
    Path("tests/fixtures/sharepoint_simulated/requests"),
    Path("tests/fixtures/sharepoint_simulated/database"),
    Path("tests/fixtures/sharepoint_simulated/identity_discoveries"),
    Path("tests/fixtures/sharepoint_simulated/windows_traceability"),
}

EXCLUDED_NAMES = {
    ".DS_Store",
    ".iam_webapp.pid",
    ".iam_launcher.pid",
    ".iam_launcher.log",
    "TEST_USERS_README.md",
}


def project_version(root: Path = ROOT) -> str:
    """Read the PEP 621 project version without importing application dependencies."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version\s*=\s*[\"']([^\"']+)[\"']", text)
    if not match:
        raise ValueError("Could not find project version in pyproject.toml")
    return match.group(1)


def git_value(root: Path, *args: str, fallback: str = "unknown") -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return result.stdout.strip() or fallback


def is_excluded(path: Path, root: Path = ROOT) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    if any(relative == excluded or excluded in relative.parents for excluded in EXCLUDED_FIXTURE_DIRS):
        return True
    if (
        path.name in EXCLUDED_NAMES
        or path.name.startswith("runtime.sqlite")
        or path.name.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm", ".accdb"))
    ):
        return True
    if path.suffix in {".pyc", ".pyo", ".log", ".pid", ".tmp"}:
        return True
    return False


def source_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for path in root.rglob("*") if path.is_file() and not is_excluded(path, root)
    )


def build_manifest(root: Path, version: str, created_at_utc: str) -> dict[str, object]:
    return {
        "package_name": "iam-automation-poc",
        "package_version": version,
        "created_at_utc": created_at_utc,
        "git_commit": git_value(root, "rev-parse", "--short", "HEAD"),
        "git_branch": git_value(root, "branch", "--show-current"),
        "git_dirty": bool(git_value(root, "status", "--porcelain", fallback="")),
        "python_minimum": ">=3.10",
        "source_distribution": True,
        "excluded_runtime_data": True,
    }


def create_archive(root: Path, output_dir: Path, version: str, include_git: bool = True) -> Path:
    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = created_at.strftime("%Y%m%d")
    commit = git_value(root, "rev-parse", "--short", "HEAD", fallback="nogit")
    # Keep the distributable filename short because Windows includes the
    # extraction directory in every nested PySide6 path.
    archive_name = f"iam-v{version}-{stamp}-{commit}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name
    # Keep the extracted tree short on Windows. The archive filename carries
    # the version metadata; it does not need to become part of every path.
    package_root = "iam_automation"

    manifest = build_manifest(root, version, created_at.isoformat())
    manifest["git_metadata_included"] = include_git

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in source_files(root):
            relative = path.relative_to(root)
            if not include_git and relative.parts and relative.parts[0] == ".github":
                continue
            archive.write(path, Path(package_root, relative).as_posix())
        archive.writestr(
            Path(package_root, "PACKAGE_MANIFEST.json").as_posix(),
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )

    return archive_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--version", help="Override the version read from pyproject.toml")
    parser.add_argument(
        "--no-git-metadata",
        action="store_true",
        help="Exclude .github files and omit reliance on Git metadata",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.version or project_version()
    archive = create_archive(ROOT, args.output_dir.resolve(), version, not args.no_git_metadata)
    print(f"[IAM] Source package created: {archive}")
    print(f"[IAM] Version: {version}")
    print("[IAM] Runtime databases, credentials, virtual environments, and generated fixture data were excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
