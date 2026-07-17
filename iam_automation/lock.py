from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class OperationLock:
    lock_id: str
    user: str
    computer: str
    process_id: int
    operation: str
    started_at: str
    expires_at: str
    database_checksum: str
    database_version: str
    application_version: str


class LockConflict(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_stale(lock: OperationLock, now: datetime | None = None) -> bool:
    return _parse_timestamp(lock.expires_at) <= (now or utc_now())


def read_lock(lock_path: Path) -> OperationLock | None:
    if not lock_path.exists():
        return None
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    return OperationLock(**data)


def acquire_lock(
    lock_path: Path,
    *,
    user: str,
    computer: str,
    operation: str,
    database_checksum: str,
    database_version: str,
    application_version: str,
    timeout_minutes: int = 20,
) -> OperationLock:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_lock(lock_path)
    if existing and not is_stale(existing):
        raise LockConflict(
            f"Active IAM operation lock exists: {existing.operation} by {existing.user} on {existing.computer}"
        )

    now = utc_now()
    lock = OperationLock(
        lock_id=str(uuid.uuid4()),
        user=user,
        computer=computer,
        process_id=os.getpid(),
        operation=operation,
        started_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=timeout_minutes)).isoformat(),
        database_checksum=database_checksum,
        database_version=database_version,
        application_version=application_version,
    )
    temp_path = lock_path.with_suffix(lock_path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(json.dumps(asdict(lock), indent=2), encoding="utf-8")
    temp_path.replace(lock_path)
    return lock


def release_lock(lock_path: Path, lock_id: str) -> bool:
    existing = read_lock(lock_path)
    if not existing or existing.lock_id != lock_id:
        return False
    lock_path.unlink()
    return True
