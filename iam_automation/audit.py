from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    audit_id: str
    timestamp: str
    user: str
    computer: str
    action: str
    entity_type: str
    entity_id: str
    previous_values: dict[str, Any]
    new_values: dict[str, Any]
    database_version: str
    application_version: str
    result: str
    error_details: str
    correlation_id: str


def append_audit_event(audit_folder: Path, event: AuditEvent) -> Path:
    audit_folder.mkdir(parents=True, exist_ok=True)
    file_path = audit_folder / f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")
    return file_path


def build_event(
    *,
    user: str,
    computer: str,
    action: str,
    result: str,
    database_version: str,
    application_version: str,
    entity_type: str = "database",
    entity_id: str = "",
    previous_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    error_details: str = "",
    correlation_id: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        audit_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        user=user,
        computer=computer,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        previous_values=previous_values or {},
        new_values=new_values or {},
        database_version=database_version,
        application_version=application_version,
        result=result,
        error_details=error_details,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )
