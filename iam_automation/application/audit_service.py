from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audit import append_audit_event, build_event


def record_audit(audit_path: Path | None, actor: str, action: str, entity_type: str, entity_id: str, *, new_values: dict[str, Any] | None = None, result: str = "SUCCESS", computer: str = "local-web") -> None:
    if audit_path is None:
        return
    append_audit_event(audit_path, build_event(user=actor, computer=computer, action=action, entity_type=entity_type, entity_id=entity_id, result=result, database_version="runtime-sqlite", application_version="local", new_values=new_values or {}))
