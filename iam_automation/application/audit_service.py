"""
File: iam_automation/application/audit_service.py
Purpose: Implements the application service for audit service workflows.
Responsibilities: Exposes or coordinates: record_audit.
Dependencies: audit
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audit import append_audit_event, build_event


def record_audit(audit_path: Path | None, actor: str, action: str, entity_type: str, entity_id: str, *, new_values: dict[str, Any] | None = None, result: str = "SUCCESS", computer: str = "local-web") -> None:
    if audit_path is None:
        return
    append_audit_event(audit_path, build_event(user=actor, computer=computer, action=action, entity_type=entity_type, entity_id=entity_id, result=result, database_version="runtime-sqlite", application_version="local", new_values=new_values or {}))
