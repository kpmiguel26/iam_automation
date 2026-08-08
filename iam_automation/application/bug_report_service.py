"""
File: iam_automation/application/bug_report_service.py
Purpose: Implements the application service for bug report service workflows.
Responsibilities: Exposes or coordinates: BugReport, BugReportService.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


BUG_STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
BUG_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ISSUE_TYPES = ("BUG", "FEATURE", "TASK", "QUESTION")
STATUS_FOLDERS = {status: status.lower() for status in BUG_STATUSES}
SEVERITY_PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
STATUS_PRIORITY = {"OPEN": 0, "IN_PROGRESS": 1, "RESOLVED": 2, "CLOSED": 3}


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
    issue_type: str = "BUG"
    comments: list[dict[str, str]] = field(default_factory=list)


class BugReportService:
    def __init__(self, sharepoint_root: Path):
        self.root = sharepoint_root / "bug_reports"

    def create(self, *, title: str, description: str, severity: str, page: str, reporter: str, computer: str, issue_type: str = "BUG") -> BugReport:
        title = title.strip()
        description = description.strip()
        severity = severity.strip().upper()
        issue_type = issue_type.strip().upper()
        if not title or not description:
            raise ValueError("Bug title and description are required.")
        if severity not in BUG_SEVERITIES:
            raise ValueError("Invalid bug severity.")
        if issue_type not in ISSUE_TYPES:
            raise ValueError("Invalid issue type.")
        bug = BugReport(str(uuid.uuid4()), title, description, severity, page.strip(), reporter, computer, self._now(), issue_type=issue_type)
        self._write(self._folder(bug.status) / self._filename(bug), bug)
        return bug

    def list_for_user(self, reporter: str, *, is_admin: bool, issue_type: str | None = None, status: str | None = None, severity: str | None = None, sort_by: str = "priority") -> list[BugReport]:
        bugs = self._load_all()
        if not is_admin:
            bugs = [bug for bug in bugs if bug.reporter.lower() == reporter.lower()]
        if not status:
            bugs = [bug for bug in bugs if bug.status != "CLOSED"]
        if issue_type:
            bugs = [bug for bug in bugs if bug.issue_type == issue_type]
        if status:
            bugs = [bug for bug in bugs if bug.status == status]
        if severity:
            bugs = [bug for bug in bugs if bug.severity == severity]
        if sort_by == "title":
            return sorted(bugs, key=lambda bug: bug.title.lower())
        if sort_by == "newest":
            return sorted(bugs, key=lambda bug: bug.created_at_utc, reverse=True)
        if sort_by == "oldest":
            return sorted(bugs, key=lambda bug: bug.created_at_utc)
        return sorted(bugs, key=lambda bug: (SEVERITY_PRIORITY.get(bug.severity, 9), STATUS_PRIORITY.get(bug.status, 9), bug.created_at_utc))

    def update(self, bug_id: str, *, status: str, assigned_to: str, resolution: str, issue_type: str | None = None) -> BugReport:
        status = status.strip().upper()
        if status not in BUG_STATUSES:
            raise ValueError("Invalid bug status.")
        if issue_type is not None:
            issue_type = issue_type.strip().upper()
            if issue_type not in ISSUE_TYPES:
                raise ValueError("Invalid issue type.")
        path, bug = self._find(bug_id)
        updated = BugReport(**{**asdict(bug), "status": status, "issue_type": issue_type or bug.issue_type, "assigned_to": assigned_to.strip() or None, "resolution": resolution.strip(), "updated_at_utc": self._now()})
        destination = self._folder(status) / path.name
        self._write(destination, updated)
        if path != destination:
            path.unlink(missing_ok=True)
        return updated

    def add_comment(self, bug_id: str, *, author: str, message: str) -> BugReport:
        author = author.strip()
        message = message.strip()
        if not author or not message:
            raise ValueError("Comment author and message are required.")
        path, bug = self._find(bug_id)
        comments = [dict(comment) for comment in bug.comments]
        comments.append({
            "comment_id": str(uuid.uuid4()),
            "author": author,
            "message": message,
            "created_at_utc": self._now(),
        })
        updated = BugReport(**{**asdict(bug), "comments": comments, "updated_at_utc": self._now()})
        self._write(path, updated)
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
        # Return the actual path so legacy long filenames remain editable after
        # upgrading to the shorter portable filename format.
        for folder in STATUS_FOLDERS.values():
            root = self.root / folder
            for path in root.glob("*.json") if root.is_dir() else ():
                try:
                    bug = BugReport(**json.loads(path.read_text(encoding="utf-8")))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if bug.bug_id == bug_id:
                    return path, bug
        raise ValueError("Bug report was not found.")

    def _path_for(self, bug: BugReport) -> Path:
        return self._folder(bug.status) / self._filename(bug)

    def _folder(self, status: str) -> Path:
        folder = self.root / STATUS_FOLDERS[status]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _filename(bug: BugReport) -> str:
        # The full timestamp and UUID made SharePoint/OneDrive paths exceed
        # Windows MAX_PATH when the package was extracted in a nested folder.
        return f"bug_{bug.bug_id.replace('-', '')[:12]}.json"

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
