"""
File: iam_automation/application/shared_notification_store.py
Purpose: Stores the database publication signal in the synchronized SharePoint workspace.
Responsibilities: Publishes the single global database snapshot event and tracks per-user reads.
Dependencies: Python standard library.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


SHARED_NOTIFICATION_SCHEMA_VERSION = 1
_NOTIFICATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STORE_LOCK = threading.RLock()


class SharedNotificationStore:
    """Small file-backed store reserved for the global publication signal."""

    def __init__(self, sharepoint_root: Path):
        self.notifications_root = (sharepoint_root / "notifications").resolve()

    def publish(
        self,
        *,
        notification_id: str,
        notification_type: str,
        title: str,
        message: str,
        recipients: list[str] | set[str],
        severity: str = "INFO",
        target_route: str = "",
        entity_type: str = "",
        entity_id: str = "",
        created_at_utc: str | None = None,
        expires_at_utc: str | None = None,
        active: bool = True,
    ) -> bool:
        """Create or refresh an event without resetting existing read markers."""
        path = self._path(notification_id)
        now = created_at_utc or datetime.now(timezone.utc).isoformat()
        normalized_recipients = self._unique_users(recipients)
        with _STORE_LOCK:
            existing = self._read(path)
            if existing is not None:
                # The original audience is immutable. A new user must wait for
                # a future notification instead of receiving old backlog items.
                normalized_recipients = self._unique_users(existing.get("recipients", normalized_recipients))
                read_by = existing.get("read_by", {})
                resolved_by = existing.get("resolved_by", {})
                created_at = str(existing.get("created_at_utc") or now)
                first_seen = str(existing.get("audience_snapshot_at_utc") or created_at)
            else:
                read_by = {}
                resolved_by = {}
                created_at = now
                first_seen = now
            payload = {
                "schema_version": SHARED_NOTIFICATION_SCHEMA_VERSION,
                "notification_id": str(notification_id),
                "notification_type": str(notification_type),
                "severity": str(severity),
                "title": str(title),
                "message": str(message),
                "entity_type": str(entity_type),
                "entity_id": str(entity_id),
                "target_route": str(target_route),
                "created_at_utc": created_at,
                "audience_snapshot_at_utc": first_seen,
                "recipients": normalized_recipients,
                "read_by": read_by if isinstance(read_by, dict) else {},
                "resolved_by": resolved_by if isinstance(resolved_by, dict) else {},
                "active": bool(active),
                "expires_at_utc": expires_at_utc if expires_at_utc is not None else (existing or {}).get("expires_at_utc"),
                "updated_at_utc": now,
            }
            self._write(path, payload)
            return existing is None

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[dict[str, object]]:
        user_key = self._user_key(username)
        now = datetime.now(timezone.utc)
        results: list[dict[str, object]] = []
        with _STORE_LOCK:
            for path in sorted(self.notifications_root.glob("*.json"), reverse=True):
                payload = self._read(path)
                if not payload or not payload.get("active", True):
                    continue
                recipients = {self._user_key(value) for value in payload.get("recipients", [])}
                if user_key not in recipients:
                    continue
                expires_at = self._parse_datetime(payload.get("expires_at_utc"))
                if expires_at and expires_at <= now:
                    continue
                read_by = payload.get("read_by", {})
                resolved_by = payload.get("resolved_by", {})
                status = "RESOLVED" if isinstance(resolved_by, dict) and user_key in resolved_by else "READ" if isinstance(read_by, dict) and user_key in read_by else "UNREAD"
                item = dict(payload)
                item["recipient_username"] = username
                item["status"] = status
                read_entry = read_by.get(user_key) if isinstance(read_by, dict) else None
                item["read_at_utc"] = read_entry.get("read_at_utc") if isinstance(read_entry, dict) else None
                results.append(item)
        # Older builds created random IDs for the same logical event (most
        # visibly, one import completion per retry). Treat type/entity as the
        # event identity when presenting the shared inbox so historical JSON
        # noise cannot appear as repeated notifications.
        grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        for item in results:
            key = (
                str(item.get("notification_type", "")),
                str(item.get("entity_type", "")),
                str(item.get("entity_id", "")),
            )
            grouped.setdefault(key, []).append(item)
        unique: list[dict[str, object]] = []
        for items in grouped.values():
            item = max(items, key=lambda value: str(value.get("created_at_utc", "")))
            statuses = {str(value.get("status", "UNREAD")) for value in items}
            if "RESOLVED" in statuses:
                item["status"] = "RESOLVED"
            elif "READ" in statuses:
                item["status"] = "READ"
            else:
                item["status"] = "UNREAD"
            if unread_only and item["status"] != "UNREAD":
                continue
            unique.append(item)
        return sorted(unique, key=lambda item: str(item.get("created_at_utc", "")), reverse=True)

    def mark_read(self, notification_id: str, username: str) -> bool:
        return self._mark_user(notification_id, username, resolved=False)

    def resolve(self, notification_id: str, username: str) -> bool:
        return self._mark_user(notification_id, username, resolved=True)

    def mark_all_read(self, username: str) -> int:
        user_key = self._user_key(username)
        now = datetime.now(timezone.utc).isoformat()
        changed = 0
        with _STORE_LOCK:
            for path in self.notifications_root.glob("*.json"):
                payload = self._read(path)
                if not payload or not payload.get("active", True):
                    continue
                recipients = {self._user_key(value) for value in payload.get("recipients", [])}
                read_by = payload.setdefault("read_by", {})
                if user_key not in recipients or user_key in read_by:
                    continue
                read_by[user_key] = {"username": username, "read_at_utc": now}
                self._write(path, payload)
                changed += 1
        return changed

    def deactivate_type_except(self, notification_type: str, active_notification_ids: set[str]) -> None:
        with _STORE_LOCK:
            for path in self.notifications_root.glob("*.json"):
                payload = self._read(path)
                if not payload or payload.get("notification_type") != notification_type:
                    continue
                if str(payload.get("notification_id")) in active_notification_ids:
                    continue
                if payload.get("active", True):
                    payload["active"] = False
                    payload["closed_at_utc"] = datetime.now(timezone.utc).isoformat()
                    self._write(path, payload)

    def _mark_user(self, notification_id: str, username: str, *, resolved: bool) -> bool:
        path = self._path(notification_id)
        user_key = self._user_key(username)
        with _STORE_LOCK:
            payload = self._read(path)
            if not payload:
                return False
            recipients = {self._user_key(value) for value in payload.get("recipients", [])}
            if user_key not in recipients:
                return False
            now = datetime.now(timezone.utc).isoformat()
            payload.setdefault("read_by", {})[user_key] = {"username": username, "read_at_utc": now}
            if resolved:
                payload.setdefault("resolved_by", {})[user_key] = {"username": username, "resolved_at_utc": now}
            self._write(path, payload)
            return True

    def _path(self, notification_id: str) -> Path:
        notification_id = str(notification_id).strip()
        if not notification_id or not _NOTIFICATION_ID_RE.fullmatch(notification_id):
            raise ValueError("Invalid shared notification identifier.")
        return self.notifications_root / f"{notification_id}.json"

    def _read(self, path: Path) -> dict[str, object] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, path: Path, payload: dict[str, object]) -> None:
        self.notifications_root.mkdir(parents=True, exist_ok=True)
        temporary = self.notifications_root / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _user_key(value: object) -> str:
        return str(value or "").strip().casefold()

    @classmethod
    def _unique_users(cls, values: object) -> list[str]:
        result: dict[str, str] = {}
        if isinstance(values, (list, tuple, set)):
            for value in values:
                username = str(value or "").strip()
                if username:
                    result.setdefault(cls._user_key(username), username)
        return sorted(result.values(), key=cls._user_key)

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
