from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity import CurrentUser


REQUEST_FILENAME_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-fA-F-]{36}\.json$")
MAX_REQUEST_BYTES = 256 * 1024
ALLOWED_OPERATION_TYPES = {"CREATE_EMPLOYEE", "UPDATE_EMPLOYEE", "DEACTIVATE_EMPLOYEE", "IMPORT_ROSTER_LOCK"}
ALLOWED_ENTITY_TYPES = {"Employee", "ImportBatch"}
REQUEST_STATUSES = {
    "PENDING",
    "IMPORTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "APPLYING",
    "APPLIED",
    "FAILED",
    "CONFLICT",
    "QUARANTINED",
}


class RequestValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ChangeRequest:
    request_id: str
    created_at_utc: str
    created_by: str
    computer_name: str
    application_version: str
    operation_type: str
    entity_type: str
    entity_id: str
    expected_record_version: int
    payload: dict[str, Any]
    reason: str
    status: str = "PENDING"
    assigned_to: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    updated_at_utc: str | None = None


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_request(
    *,
    user: CurrentUser,
    application_version: str,
    operation_type: str,
    entity_type: str,
    entity_id: str,
    expected_record_version: int,
    payload: dict[str, Any],
    reason: str,
) -> ChangeRequest:
    if not user.can_submit_requests:
        raise PermissionError(f"User cannot submit change requests: {user.username}")
    request = ChangeRequest(
        request_id=str(uuid.uuid4()),
        created_at_utc=utc_timestamp(),
        created_by=user.username,
        computer_name=user.computer,
        application_version=application_version,
        operation_type=operation_type,
        entity_type=entity_type,
        entity_id=entity_id,
        expected_record_version=expected_record_version,
        payload=payload,
        reason=reason,
    )
    validate_request_dict(asdict(request))
    return request


def request_filename(request: ChangeRequest) -> str:
    return f"{filename_timestamp()}_{request.request_id}.json"


def submit_request(request: ChangeRequest, pending_folder: Path) -> Path:
    pending_folder.mkdir(parents=True, exist_ok=True)
    path = pending_folder / request_filename(request)
    temp_path = path.with_suffix(".tmp")
    data = json.dumps(asdict(request), indent=2, sort_keys=True)
    with temp_path.open("x", encoding="utf-8") as handle:
        handle.write(data)
        handle.write("\n")
    temp_path.replace(path)
    return path


def load_request_file(path: Path) -> ChangeRequest:
    if not REQUEST_FILENAME_RE.match(path.name):
        raise RequestValidationError(f"Invalid request filename: {path.name}")
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise RequestValidationError(f"Request file is too large: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RequestValidationError(f"Invalid JSON: {path.name}") from exc
    validate_request_dict(data)
    return ChangeRequest(**data)


def validate_request_dict(data: dict[str, Any]) -> None:
    required = {
        "request_id",
        "created_at_utc",
        "created_by",
        "computer_name",
        "application_version",
        "operation_type",
        "entity_type",
        "entity_id",
        "expected_record_version",
        "payload",
        "reason",
        "status",
    }
    optional = {"assigned_to", "reviewed_by", "review_note", "updated_at_utc"}
    unknown = set(data) - required - optional
    missing = required - set(data)
    if missing:
        raise RequestValidationError(f"Missing request fields: {sorted(missing)}")
    if unknown:
        raise RequestValidationError(f"Unknown request fields: {sorted(unknown)}")
    try:
        uuid.UUID(str(data["request_id"]))
    except ValueError as exc:
        raise RequestValidationError("request_id must be a UUID") from exc
    if data["operation_type"] not in ALLOWED_OPERATION_TYPES:
        raise RequestValidationError(f"Unsupported operation_type: {data['operation_type']}")
    if data["entity_type"] not in ALLOWED_ENTITY_TYPES:
        raise RequestValidationError(f"Unsupported entity_type: {data['entity_type']}")
    if data["status"] not in REQUEST_STATUSES:
        raise RequestValidationError(f"Unsupported status: {data['status']}")
    if not isinstance(data["expected_record_version"], int) or data["expected_record_version"] < 0:
        raise RequestValidationError("expected_record_version must be a non-negative integer")
    if not isinstance(data["payload"], dict) or not data["payload"]:
        raise RequestValidationError("payload must be a non-empty object")
    for key in ("created_by", "computer_name", "application_version", "entity_id", "reason"):
        if not str(data.get(key, "")).strip():
            raise RequestValidationError(f"{key} is required")


def request_ids_from_jsonl(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = str(item.get("request_id", "")).strip()
            if request_id:
                ids.add(request_id)
    return ids


def append_processed_registry(path: Path, request: ChangeRequest, *, batch_id: str, result: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "request_id": request.request_id,
        "batch_id": batch_id,
        "result": result,
        "recorded_at_utc": utc_timestamp(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def import_pending_requests(
    *,
    pending_folder: Path,
    imported_folder: Path,
    quarantine_folder: Path,
    processed_registry_path: Path,
    batch_id: str,
) -> dict[str, Any]:
    imported_folder.mkdir(parents=True, exist_ok=True)
    quarantine_folder.mkdir(parents=True, exist_ok=True)
    processed_ids = request_ids_from_jsonl(processed_registry_path)
    summary: dict[str, Any] = {
        "batch_id": batch_id,
        "imported": [],
        "duplicates": [],
        "quarantined": [],
    }
    if not pending_folder.exists():
        return summary
    for path in sorted(pending_folder.glob("*.json")):
        try:
            request = load_request_file(path)
            if request.status != "PENDING":
                raise RequestValidationError("Only PENDING request files can be imported.")
            if request.request_id in processed_ids:
                target = quarantine_folder / path.name
                shutil.move(str(path), str(target))
                summary["duplicates"].append({"path": str(target), "request_id": request.request_id})
                continue
            target = imported_folder / path.name
            shutil.move(str(path), str(target))
            append_processed_registry(processed_registry_path, request, batch_id=batch_id, result="IMPORTED")
            processed_ids.add(request.request_id)
            summary["imported"].append({"path": str(target), "request_id": request.request_id})
        except Exception as exc:
            target = quarantine_folder / path.name
            shutil.move(str(path), str(target))
            summary["quarantined"].append({"path": str(target), "error": str(exc)})
    return summary
