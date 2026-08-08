"""
File: iam_automation/application/governance_service.py
Purpose: Implements the application service for governance service workflows.
Responsibilities: Exposes or coordinates: GovernanceService.
Dependencies: audit, runtime_sync, publication_state
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..audit import append_audit_event, build_event
from ..runtime_sync import RuntimeSnapshot, publish_runtime_snapshot, sha256_file
from .publication_state import clear_publication_pending


class GovernanceService:
    def __init__(self, *, local_runtime_path: Path, published_runtime_path: Path, audit_path: Path):
        self.local_runtime_path = local_runtime_path
        self.published_runtime_path = published_runtime_path
        self.audit_path = audit_path

    def published_checksum(self) -> str:
        return sha256_file(self.published_runtime_path) if self.published_runtime_path.exists() else ""

    def publish(self, actor: str, expected_checksum: str | None = None) -> RuntimeSnapshot:
        snapshot = publish_runtime_snapshot(self.local_runtime_path, self.published_runtime_path, actor=actor, expected_checksum=expected_checksum or None)
        clear_publication_pending(self.local_runtime_path)
        self._audit(actor, "PUBLISH_RUNTIME_SNAPSHOT", "SUCCESS", {"checksum": snapshot.checksum})
        return snapshot

    def restore(self, actor: str, backup_name: str) -> RuntimeSnapshot:
        backup = (self.published_runtime_path.parent / "backups" / backup_name).resolve()
        backup_root = (self.published_runtime_path.parent / "backups").resolve()
        if backup.parent != backup_root or not backup.is_file() or backup.suffix != ".sqlite":
            raise ValueError("The selected runtime backup is invalid.")
        snapshot = publish_runtime_snapshot(backup, self.published_runtime_path, actor=actor)
        clear_publication_pending(self.local_runtime_path)
        self._audit(actor, "RESTORE_RUNTIME_SNAPSHOT", "SUCCESS", {"backup": backup.name, "checksum": snapshot.checksum})
        return snapshot

    def list_backups(self) -> list[Path]:
        folder = self.published_runtime_path.parent / "backups"
        return sorted(folder.glob("*.sqlite"), reverse=True) if folder.exists() else []

    def list_audit_events(self, limit: int = 100) -> list[dict]:
        events: list[dict] = []
        for path in sorted(self.audit_path.glob("audit_*.jsonl"), reverse=True):
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    return events
        return events

    def _audit(self, actor: str, action: str, result: str, new_values: dict) -> None:
        append_audit_event(self.audit_path, build_event(user=actor, computer="local-web", action=action, result=result, database_version="runtime-sqlite", application_version="local", new_values=new_values))
