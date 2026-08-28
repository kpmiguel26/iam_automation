"""
File: iam_automation/application/local_notification_store.py
Purpose: Stores per-workstation notifications outside the runtime database.
Responsibilities: Persists local notification payloads and their user lifecycle.
Dependencies: Python standard library.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCAL_NOTIFICATION_SCHEMA_VERSION = 1
_NOTIFICATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STORE_LOCK = threading.RLock()


class LocalNotificationStore:
    """File-backed notification store scoped to one local runtime copy."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def upsert(
        self,
        *,
        notification_id: str,
        recipient_username: str,
        notification_type: str,
        title: str,
        message: str,
        severity: str = "INFO",
        target_route: str = "",
        entity_type: str = "",
        entity_id: str = "",
        created_at_utc: str | None = None,
        expires_at_utc: str | None = None,
        reactivate_expired: bool = False,
    ) -> bool:
        path = self._path(recipient_username, notification_id)
        now = created_at_utc or datetime.now(timezone.utc).isoformat()
        with _STORE_LOCK:
            existing = self._read(path)
            was_expired = str((existing or {}).get("status", "")) == "EXPIRED"
            status = str((existing or {}).get("status", "UNREAD"))
            read_at = (existing or {}).get("read_at_utc")
            if reactivate_expired and status == "EXPIRED":
                status = "UNREAD"
                read_at = None
            payload: dict[str, Any] = {
                "schema_version": LOCAL_NOTIFICATION_SCHEMA_VERSION,
                "notification_id": str(notification_id),
                "recipient_username": str(recipient_username),
                "notification_type": str(notification_type),
                "severity": str(severity),
                "title": str(title),
                "message": str(message),
                "entity_type": str(entity_type),
                "entity_id": str(entity_id),
                "target_route": str(target_route),
                "status": status,
                "created_at_utc": str((existing or {}).get("created_at_utc") or now),
                "read_at_utc": read_at,
                "expires_at_utc": expires_at_utc,
                "updated_at_utc": now,
            }
            self._write(path, payload)
            return existing is None or (reactivate_expired and was_expired)

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[dict[str, Any]]:
        user_root = self._user_root(username)
        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        with _STORE_LOCK:
            for path in user_root.glob("*.json"):
                payload = self._read(path)
                if not payload:
                    continue
                self._expire_if_due(path, payload, now)
                if unread_only and str(payload.get("status", "UNREAD")) != "UNREAD":
                    continue
                results.append(payload)
        return sorted(results, key=lambda item: str(item.get("created_at_utc", "")), reverse=True)

    def count_unread(self, username: str) -> int:
        return len(self.list_for_user(username, unread_only=True))

    def mark_read(self, username: str, notification_id: str) -> bool:
        return self._set_status(username, notification_id, "READ")

    def resolve(self, username: str, notification_id: str) -> bool:
        return self._set_status(username, notification_id, "RESOLVED", preserve_read=True)

    def set_status(self, username: str, notification_id: str, status: str) -> bool:
        return self._set_status(username, notification_id, status, preserve_read=status in {"READ", "RESOLVED", "EXPIRED"})

    def mark_all_read(self, username: str) -> int:
        changed = 0
        for item in self.list_for_user(username, unread_only=True):
            changed += int(self.mark_read(username, str(item.get("notification_id", ""))))
        return changed

    def expire(self, username: str | None = None) -> int:
        now = datetime.now(timezone.utc)
        roots = [self._user_root(username)] if username else list(self.root.glob("user-*"))
        changed = 0
        with _STORE_LOCK:
            for user_root in roots:
                for path in user_root.glob("*.json"):
                    payload = self._read(path)
                    if payload and self._expire_if_due(path, payload, now):
                        changed += 1
        return changed

    def list_all(self, *, notification_type: str | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with _STORE_LOCK:
            for path in self.root.glob("user-*/*.json"):
                payload = self._read(path)
                if payload and (notification_type is None or payload.get("notification_type") == notification_type):
                    results.append(payload)
        return results

    def get(self, username: str, notification_id: str) -> dict[str, Any] | None:
        with _STORE_LOCK:
            return self._read(self._path(username, notification_id))

    def _set_status(self, username: str, notification_id: str, status: str, *, preserve_read: bool = False) -> bool:
        path = self._path(username, notification_id)
        with _STORE_LOCK:
            payload = self._read(path)
            if not payload:
                return False
            payload["status"] = status
            if preserve_read or status in {"READ", "RESOLVED", "EXPIRED"}:
                payload["read_at_utc"] = payload.get("read_at_utc") or datetime.now(timezone.utc).isoformat()
            payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            self._write(path, payload)
            return True

    def _expire_if_due(self, path: Path, payload: dict[str, Any], now: datetime) -> bool:
        expires = self._parse_datetime(payload.get("expires_at_utc"))
        if expires and expires <= now and str(payload.get("status", "UNREAD")) in {"UNREAD", "READ"}:
            payload["status"] = "EXPIRED"
            payload["read_at_utc"] = payload.get("read_at_utc") or now.isoformat()
            payload["updated_at_utc"] = now.isoformat()
            self._write(path, payload)
            return True
        return False

    def _path(self, username: str, notification_id: str) -> Path:
        notification_id = str(notification_id).strip()
        if not notification_id or not _NOTIFICATION_ID_RE.fullmatch(notification_id):
            raise ValueError("Invalid local notification identifier.")
        return self._user_root(username) / f"{notification_id}.json"

    def _user_root(self, username: str) -> Path:
        user_key = str(username or "").strip().casefold()
        digest = hashlib.sha256(user_key.encode("utf-8")).hexdigest()[:24]
        return self.root / f"user-{digest}"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
