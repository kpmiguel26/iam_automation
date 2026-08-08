"""
File: iam_automation/application/master_admin_service.py
Purpose: Implements the application service for master admin service workflows.
Responsibilities: Exposes or coordinates: MasterAdminService.
Dependencies: sqlalchemy, audit, identity, infrastructure, user_service
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..audit import append_audit_event, build_event
from ..identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, normalize_role
from ..infrastructure.sqlite.orm import SystemProfileModel, orm_session
from .user_service import UserService


DEFAULT_SETTINGS = {
    "approval_sla_hours": {"CREATE_EMPLOYEE": 24, "UPDATE_EMPLOYEE": 16, "DEACTIVATE_EMPLOYEE": 8},
    "strict_identity_gate": False,
    "break_glass_enabled": True,
    "temporary_super_operator_enabled": True,
}


class MasterAdminService:
    def __init__(self, database_path: Path, audit_path: Path):
        self.database_path = database_path
        self.audit_path = audit_path
        self.users = UserService(database_path)

    def list_administrators(self):
        return [user for user in self.users.list_users() if {normalize_role(role) for role in user.roles} & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}]

    def save_administrator(self, username: str, display_name: str, password: str, roles: list[str], active: bool) -> None:
        normalized = {normalize_role(role) for role in roles}
        if not normalized & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
            raise ValueError("An administrator must have Application Administrator or Master Administrator access.")
        existing = next((user for user in self.list_administrators() if user.username.lower() == username.strip().lower()), None)
        if existing:
            self.users.update_user(username, display_name=display_name, password=password, roles=list(normalized), active=active)
        else:
            self.users.create_user(username, display_name, password, list(normalized))
        self.record("ADMINISTRATOR_SAVED", "Application administrator updated", username)

    def settings(self) -> dict:
        with orm_session(self.database_path) as session:
            row = session.get(SystemProfileModel, "global_settings")
            return {**DEFAULT_SETTINGS, **(json.loads(row.profile_json) if row else {})}

    def save_settings(self, values: dict, actor: str) -> dict:
        current = self.settings()
        try:
            sla = {key: max(1, int(value)) for key, value in values.get("approval_sla_hours", current["approval_sla_hours"]).items()}
        except (TypeError, ValueError) as exc:
            raise ValueError("SLA hours must be positive whole numbers.") from exc
        updated = {"approval_sla_hours": sla, "strict_identity_gate": bool(values.get("strict_identity_gate", False)), "break_glass_enabled": bool(values.get("break_glass_enabled", True)), "temporary_super_operator_enabled": bool(values.get("temporary_super_operator_enabled", current.get("temporary_super_operator_enabled", True)))}
        with orm_session(self.database_path) as session:
            row = session.get(SystemProfileModel, "global_settings")
            if row is None:
                session.add(SystemProfileModel(profile_name="global_settings", profile_json=json.dumps(updated, sort_keys=True), active=True))
            else:
                row.profile_json = json.dumps(updated, sort_keys=True)
        self.record("GLOBAL_SETTINGS_UPDATED", "Global security and SLA settings updated", actor, new_values=updated)
        return updated

    def break_glass(self, actor: str, reason: str, operation: str) -> None:
        if not reason.strip() or not operation.strip():
            raise ValueError("Break-glass operation and reason are required.")
        if not self.settings().get("break_glass_enabled", True):
            raise PermissionError("Break-glass operations are disabled by global settings.")
        self.record("BREAK_GLASS", operation.strip(), actor, result="AUTHORIZED", new_values={"reason": reason.strip()})

    def record(self, action: str, entity: str, actor: str, *, result: str = "SUCCESS", new_values: dict | None = None) -> None:
        append_audit_event(self.audit_path, build_event(user=actor, computer="local-web", action=action, entity_type="administration", entity_id=entity, result=result, database_version="runtime-sqlite", application_version="local", new_values=new_values or {}))

    def audit_events(self, limit: int = 500) -> list[dict]:
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

    def export_audit(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.audit_events(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return destination

    def archive_audit(self, actor: str) -> Path:
        archive = self.audit_path / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        files = list(self.audit_path.glob("audit_*.jsonl"))
        for path in files:
            shutil.copy2(path, archive / path.name)
        self.record("AUDIT_ARCHIVED", "audit", actor, new_values={"files": len(files), "archive": str(archive)})
        return archive
