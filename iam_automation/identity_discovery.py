from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DISCOVERY_FILENAME = "iam_identity_discovery.json"
DISCOVERY_DIRECTORY = "identity_discoveries"
DISCOVERY_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class IdentityDiscovery:
    discovery_id: str
    username: str
    computer: str
    suggested_role: str
    status: str
    discovered_at_utc: str


def discovery_path(sharepoint_root: Path) -> Path:
    return sharepoint_root / "database" / "snapshots" / DISCOVERY_DIRECTORY


def _read(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": DISCOVERY_SCHEMA_VERSION, "discoveries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Identity discovery JSON could not be read: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("discoveries", []), list):
        raise RuntimeError(f"Identity discovery JSON has an invalid structure: {path}")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def record_identity_discovery(path: Path, username: str, computer: str, suggested_role: str) -> IdentityDiscovery:
    if (path.exists() and path.is_dir()) or path.suffix == "":
        path.mkdir(parents=True, exist_ok=True)
        normalized = username.strip().lower()
        for item in _list_directory(path):
            if item.username.lower() == normalized and item.computer == computer and item.status == "PENDING":
                return item
        discovery = IdentityDiscovery(str(uuid.uuid4()), username.strip(), computer, suggested_role.strip().upper(), "PENDING", datetime.now(timezone.utc).isoformat())
        _write(path / f"identity_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{discovery.discovery_id}.json", {"schema_version": DISCOVERY_SCHEMA_VERSION, "discoveries": [discovery.__dict__]})
        return discovery
    data = _read(path)
    normalized = username.strip().lower()
    for item in data["discoveries"]:
        if str(item.get("username", "")).strip().lower() == normalized and item.get("status") == "PENDING":
            return IdentityDiscovery(str(item["discovery_id"]), str(item["username"]), str(item.get("computer", "")), str(item.get("suggested_role", suggested_role)), "PENDING", str(item.get("discovered_at_utc", "")))
    discovery = IdentityDiscovery(str(uuid.uuid4()), username.strip(), computer, suggested_role.strip().upper(), "PENDING", datetime.now(timezone.utc).isoformat())
    data["schema_version"] = DISCOVERY_SCHEMA_VERSION
    data["discoveries"].append(discovery.__dict__)
    _write(path, data)
    return discovery


def list_pending_discoveries(path: Path) -> list[IdentityDiscovery]:
    if path.is_dir():
        return [item for item in _list_directory(path) if item.status == "PENDING"]
    data = _read(path)
    return [IdentityDiscovery(str(item["discovery_id"]), str(item["username"]), str(item.get("computer", "")), str(item.get("suggested_role", "AUDITOR")), str(item.get("status", "PENDING")), str(item.get("discovered_at_utc", ""))) for item in data["discoveries"] if item.get("status") == "PENDING"]


def get_pending_discovery(path: Path, discovery_id: str) -> IdentityDiscovery | None:
    return next((item for item in list_pending_discoveries(path) if item.discovery_id == discovery_id), None)


def mark_discovery(path: Path, discovery_id: str, status: str, actor: str) -> None:
    if path.is_dir():
        for file_path in sorted(path.glob("*.json")):
            data = _read(file_path)
            if any(str(item.get("discovery_id")) == discovery_id for item in data["discoveries"]):
                for item in data["discoveries"]:
                    if str(item.get("discovery_id")) == discovery_id:
                        item["status"] = status
                        item["processed_by"] = actor
                        item["processed_at_utc"] = datetime.now(timezone.utc).isoformat()
                _write(file_path, data)
                return
        raise KeyError(f"Identity discovery was not found: {discovery_id}")
    data = _read(path)
    for item in data["discoveries"]:
        if str(item.get("discovery_id")) == discovery_id:
            item["status"] = status
            item["processed_by"] = actor
            item["processed_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write(path, data)
            return
    raise KeyError(f"Identity discovery was not found: {discovery_id}")


def _list_directory(path: Path) -> list[IdentityDiscovery]:
    discoveries: list[IdentityDiscovery] = []
    for file_path in sorted(path.glob("*.json")):
        data = _read(file_path)
        discoveries.extend(
            IdentityDiscovery(str(item["discovery_id"]), str(item["username"]), str(item.get("computer", "")), str(item.get("suggested_role", "AUDITOR")), str(item.get("status", "PENDING")), str(item.get("discovered_at_utc", "")))
            for item in data["discoveries"]
        )
    return discoveries
