"""
File: iam_automation/application/notification_service.py
Purpose: Coordinates local and explicitly global notification workflows.
Responsibilities: Stores operational notifications locally and publishes only
the database publication signal to the synchronized workspace.
Dependencies: sqlalchemy, infrastructure, local_notification_store,
shared_notification_store.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from ..infrastructure.sqlite.orm import AppUserModel, UserRoleModel, orm_session
from .local_notification_store import LocalNotificationStore
from .shared_notification_store import SharedNotificationStore


GLOBAL_NOTIFICATION_TYPES = frozenset({"DATABASE_SNAPSHOT_PUBLISHED"})
GLOBAL_NOTIFICATION_THROTTLE_SECONDS = 5 * 60


@dataclass(frozen=True)
class Notification:
    notification_id: str
    recipient_username: str
    notification_type: str
    severity: str
    title: str
    message: str
    target_route: str
    status: str
    entity_type: str
    entity_id: str
    created_at_utc: str
    read_at_utc: str | None
    expires_at_utc: str | None


class NotificationService:
    def __init__(
        self,
        database_path: Path,
        *,
        sharepoint_root: Path | None = None,
        local_root: Path | None = None,
    ):
        self.database_path = database_path
        self.local_store = LocalNotificationStore(local_root or database_path.parent / ".iam_notifications")
        self.shared_store = SharedNotificationStore(sharepoint_root) if sharepoint_root else None

    def unread_count(self, username: str) -> int:
        return self.local_store.count_unread(username) + len(self._shared_notifications_for_user(username, unread_only=True))

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[Notification]:
        local_items = [
            self._from_payload(item)
            for item in self.local_store.list_for_user(username, unread_only=unread_only)
        ]
        shared_items = [
            self._from_shared_notification(item)
            for item in self._shared_notifications_for_user(username, unread_only=unread_only)
        ]
        return sorted(local_items + shared_items, key=lambda item: item.created_at_utc, reverse=True)

    def mark_all_read(self, username: str) -> int:
        local_count = self.local_store.mark_all_read(username)
        shared_count = 0
        for item in self._shared_notifications_for_user(username, unread_only=True):
            if self.shared_store and self.shared_store.mark_read(str(item["notification_id"]), username):
                shared_count += 1
        return local_count + shared_count

    def create(
        self,
        recipient_username: str,
        notification_type: str,
        title: str,
        message: str,
        *,
        severity: str = "INFO",
        target_route: str = "",
        entity_type: str = "",
        entity_id: str = "",
        expires_at_utc: str | None = None,
        notification_id: str | None = None,
    ) -> str:
        notification_id = str(notification_id or uuid.uuid4())
        self.local_store.upsert(
            notification_id=notification_id,
            recipient_username=recipient_username,
            notification_type=notification_type,
            title=title,
            message=message,
            severity=severity,
            target_route=target_route,
            entity_type=entity_type,
            entity_id=entity_id,
            expires_at_utc=expires_at_utc,
        )
        return notification_id

    def publish_database_snapshot(
        self,
        snapshot_checksum: str,
        *,
        actor: str,
        recipients: Iterable[str],
        reconciled_count: int = 0,
    ) -> str:
        """Publish the only notification that is intentionally global.

        The shared event is throttled so repeated publishes within five
        minutes do not create or rewrite OneDrive-synchronized notification
        files. The runtime database itself remains the source of the update.
        """
        if not self.shared_store:
            raise RuntimeError("A SharePoint workspace is required for the database publication notification.")
        snapshot_checksum = str(snapshot_checksum).strip()
        if not snapshot_checksum:
            raise ValueError("A database snapshot checksum is required for the publication notification.")

        now = datetime.now(timezone.utc)
        latest = self.shared_store.latest_active("DATABASE_SNAPSHOT_PUBLISHED")
        if latest:
            latest_at = self._parse_datetime(latest.get("updated_at_utc") or latest.get("created_at_utc"))
            if latest_at and (now - latest_at).total_seconds() < GLOBAL_NOTIFICATION_THROTTLE_SECONDS:
                return str(latest.get("notification_id", ""))

        notification_id = hashlib.sha256(f"database-snapshot:{snapshot_checksum}".encode("utf-8")).hexdigest()
        self.shared_store.deactivate_type_except("DATABASE_SNAPSHOT_PUBLISHED", set())
        self.shared_store.publish(
            notification_id=notification_id,
            notification_type="DATABASE_SNAPSHOT_PUBLISHED",
            severity="CRITICAL",
            title="Critical: new database snapshot published",
            message=(
                f"A new runtime SQLite snapshot was published by {actor}. "
                f"Other workstations can refresh to receive the approved changes. "
                f"{reconciled_count} request(s) were applied locally before publication."
            ),
            recipients=set(recipients),
            entity_type="runtime_snapshot",
            entity_id=snapshot_checksum,
            target_route="/admin/governance",
            created_at_utc=now.isoformat(),
        )
        return notification_id

    def notify_request_reviewers(
        self,
        request_id: str,
        operation_type: str,
        created_by: str,
        *,
        record_count: int = 0,
    ) -> int:
        """Create one local review notification for every eligible user."""
        role_names = ("REVIEWER", "APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        message = (
            f"{operation_type.replace('_', ' ').title()} request {request_id[:8]} "
            f"is ready for review ({record_count} record(s)). Submitted by {created_by}."
        )
        recipients = self._recipients(role_names)
        for username in recipients:
            notification_id = hashlib.sha256(f"request-review:{username.lower()}:{request_id}".encode("utf-8")).hexdigest()
            self.create(
                username,
                "REQUEST_REVIEW_REQUIRED",
                "Request ready for review",
                message,
                severity="WARNING",
                entity_type="change_request",
                entity_id=request_id,
                target_route="/admin/approvals",
                notification_id=notification_id,
            )
        return len(recipients)

    def notify_source_update_available(self, request_id: str, operation_type: str, record_count: int) -> int:
        """Create local administrator notifications for staged source data."""
        role_names = ("APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        message = (
            f"{record_count} source record(s) from {operation_type.replace('_', ' ').title()} "
            "are waiting in Employee Updates. No employee was created automatically."
        )
        recipients = self._recipients(role_names)
        for username in recipients:
            notification_id = hashlib.sha256(f"source-update:{username.lower()}:{request_id}".encode("utf-8")).hexdigest()
            self.create(
                username,
                "SOURCE_UPDATE_AVAILABLE",
                "Source update ready for individual review",
                message,
                severity="WARNING",
                entity_type="change_request",
                entity_id=request_id,
                target_route="/employees/source-updates",
                notification_id=notification_id,
            )
        return len(recipients)

    def mark_read(self, username: str, notification_id: str) -> None:
        if self.local_store.mark_read(username, notification_id):
            return
        if self._shared_notification_belongs_to_user(notification_id, username) and self.shared_store:
            self.shared_store.mark_read(notification_id, username)

    def resolve(self, username: str, notification_id: str) -> None:
        if self.local_store.resolve(username, notification_id):
            return
        if self._shared_notification_belongs_to_user(notification_id, username) and self.shared_store:
            self.shared_store.resolve(notification_id, username)

    def expire(self, username: str | None = None) -> int:
        return self.local_store.expire(username)

    def _recipients(self, role_names: tuple[str, ...]) -> set[str]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(
                select(AppUserModel)
                .join(UserRoleModel)
                .where(
                    AppUserModel.active.is_(True),
                    AppUserModel.status == "ACTIVE",
                    UserRoleModel.role_name.in_(role_names),
                )
            ).all()
            return {row.username for row in rows}

    def _shared_notifications_for_user(self, username: str, *, unread_only: bool = False) -> list[dict[str, object]]:
        if not self.shared_store:
            return []
        return [
            item
            for item in self.shared_store.list_for_user(username, unread_only=unread_only)
            if str(item.get("notification_type", "")) in GLOBAL_NOTIFICATION_TYPES
        ]

    def _shared_notification_belongs_to_user(self, notification_id: str, username: str) -> bool:
        return any(
            str(item.get("notification_id", "")) == str(notification_id)
            for item in self._shared_notifications_for_user(username)
        )

    @staticmethod
    def _from_payload(item: dict[str, object]) -> Notification:
        target_route = str(item.get("target_route", ""))
        if str(item.get("notification_type", "")) == "FILE_DETECTED" and "/requests/pending/" in str(item.get("entity_id", "")):
            target_route = "/admin/approvals"
        return Notification(
            str(item.get("notification_id", "")),
            str(item.get("recipient_username", "")),
            str(item.get("notification_type", "")),
            str(item.get("severity", "INFO")),
            str(item.get("title", "")),
            str(item.get("message", "")),
            target_route,
            str(item.get("status", "UNREAD")),
            str(item.get("entity_type", "")),
            str(item.get("entity_id", "")),
            str(item.get("created_at_utc", "")),
            str(item.get("read_at_utc")) if item.get("read_at_utc") else None,
            str(item.get("expires_at_utc")) if item.get("expires_at_utc") else None,
        )

    @staticmethod
    def _from_shared_notification(item: dict[str, object]) -> Notification:
        return Notification(
            str(item.get("notification_id", "")),
            str(item.get("recipient_username", "")),
            str(item.get("notification_type", "")),
            str(item.get("severity", "INFO")),
            str(item.get("title", "")),
            str(item.get("message", "")),
            str(item.get("target_route", "")),
            str(item.get("status", "UNREAD")),
            str(item.get("entity_type", "")),
            str(item.get("entity_id", "")),
            str(item.get("created_at_utc", "")),
            str(item.get("read_at_utc")) if item.get("read_at_utc") else None,
            str(item.get("expires_at_utc")) if item.get("expires_at_utc") else None,
        )

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
