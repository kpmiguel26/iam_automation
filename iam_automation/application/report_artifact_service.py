"""Persist generated report artifacts in the shared flat reports directory."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ReportArtifactService:
    """Store report exports in one engine-agnostic directory without overwrites."""

    def __init__(self, workspace_root: Path):
        self.reports_directory = Path(workspace_root) / "reports"

    def save(self, filename: str, content: bytes) -> Path:
        source_name = Path(filename).name
        if not source_name or source_name != filename:
            raise ValueError("Report filenames must not contain directory components.")
        stem = Path(source_name).stem
        suffix = Path(source_name).suffix
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_") or "report"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.reports_directory / f"{safe_stem}_{timestamp}_{uuid.uuid4().hex[:8]}{suffix}"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        self.reports_directory.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
