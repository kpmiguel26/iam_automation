from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


BUG_STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
BUG_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
STATUS_FOLDERS = {status: status.lower() for status in BUG_STATUSES}


@dataclass(frozen=True)
class BugReport:
    bug_id: str
    title: str
    description: str
    severity: str
    page: str
    reporter: str
    computer: str
    created_at_utc: str
    status: str = "OPEN"
    assigned_to: str | None = None
    resolution: str = ""
    updated_at_utc: str | None = None


class BugReportService:
    def __init__(self, sharepoint_root: Path):
        self.root = sharepoint_root / "bug_reports"

    def create(self, *, title: str, description: str, severity: str, page: str, reporter: str, computer: str) -> BugReport:
        title = title.strip()
        description = description.strip()
        severity = severity.strip().upper()
        if not title or not description:
            raise ValueError("Bug title and description are required.")
        if severity not in BUG_SEVERITIES:
            raise ValueError("Invalid bug severity.")
        bug = BugReport(str(uuid.uuid4()), title, description, severity, page.strip(), reporter, computer, self._now())
        self._write(self._folder(bug.status) / self._filename(bug), bug)
        return bug

    def list_for_user(self, reporter: str, *, is_admin: bool) -> list[BugReport]:
        bugs = self._load_all()
        if not is_admin:
            bugs = [bug for bug in bugs if bug.reporter.lower() == reporter.lower()]
        return sorted(bugs, key=lambda bug: bug.created_at_utc, reverse=True)

    def update(self, bug_id: str, *, status: str, assigned_to: str, resolution: str) -> BugReport:
        status = status.strip().upper()
        if status not in BUG_STATUSES:
            raise ValueError("Invalid bug status.")
        path, bug = self._find(bug_id)
        updated = BugReport(**{**asdict(bug), "status": status, "assigned_to": assigned_to.strip() or None, "resolution": resolution.strip(), "updated_at_utc": self._now()})
        destination = self._folder(status) / path.name
        self._write(destination, updated)
        if path != destination:
            path.unlink(missing_ok=True)
        return updated

    def _load_all(self) -> list[BugReport]:
        bugs: list[BugReport] = []
        for folder in STATUS_FOLDERS.values():
            for path in (self.root / folder).glob("*.json") if (self.root / folder).is_dir() else ():
                try:
                    bugs.append(BugReport(**json.loads(path.read_text(encoding="utf-8"))))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        return bugs

    def _find(self, bug_id: str) -> tuple[Path, BugReport]:
        for bug in self._load_all():
            if bug.bug_id == bug_id:
                return self._path_for(bug), bug
        raise ValueError("Bug report was not found.")

    def _path_for(self, bug: BugReport) -> Path:
        return self._folder(bug.status) / self._filename(bug)

    def _folder(self, status: str) -> Path:
        folder = self.root / STATUS_FOLDERS[status]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _filename(bug: BugReport) -> str:
        timestamp = bug.created_at_utc.replace("-", "").replace(":", "").replace("+00:00", "Z")
        return f"{timestamp}_{bug.bug_id}.json"

    @staticmethod
    def _write(path: Path, bug: BugReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(bug), handle, indent=2, sort_keys=True)
                handle.write("\n")
            Path(temporary).replace(path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
