from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import NotificationModel, orm_session


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
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def unread_count(self, username: str) -> int:
        self.expire(username)
        with orm_session(self.database_path) as session:
            return int(session.scalar(select(func.count(NotificationModel.notification_id)).where(
                NotificationModel.recipient_username == username,
                NotificationModel.status == "UNREAD",
            )) or 0)

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[Notification]:
        self.expire(username)
        statement = select(NotificationModel).where(NotificationModel.recipient_username == username).order_by(NotificationModel.created_at_utc.desc())
        if unread_only:
            statement = statement.where(NotificationModel.status == "UNREAD")
        with orm_session(self.database_path) as session:
            return [self._to_notification(row) for row in session.scalars(statement).all()]

    def mark_all_read(self, username: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(NotificationModel).where(NotificationModel.recipient_username == username, NotificationModel.status == "UNREAD")).all()
            for row in rows:
                row.status = "READ"
                row.read_at_utc = now
            return len(rows)

    def create(self, recipient_username: str, notification_type: str, title: str, message: str, *, severity: str = "INFO", target_route: str = "", entity_type: str = "", entity_id: str = "", expires_at_utc: str | None = None) -> str:
        notification_id = str(uuid.uuid4())
        with orm_session(self.database_path) as session:
            session.add(NotificationModel(
                notification_id=notification_id,
                recipient_username=recipient_username,
                notification_type=notification_type,
                severity=severity,
                title=title,
                message=message,
                entity_type=entity_type,
                entity_id=entity_id,
                target_route=target_route,
                status="UNREAD",
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                expires_at_utc=expires_at_utc,
            ))
        return notification_id

    def mark_read(self, username: str, notification_id: str) -> None:
        with orm_session(self.database_path) as session:
            row = session.scalar(select(NotificationModel).where(
                NotificationModel.notification_id == notification_id,
                NotificationModel.recipient_username == username,
            ))
            if row:
                row.status = "READ"
                row.read_at_utc = datetime.now(timezone.utc).isoformat()

    def resolve(self, username: str, notification_id: str) -> None:
        with orm_session(self.database_path) as session:
            row = session.scalar(select(NotificationModel).where(NotificationModel.notification_id == notification_id, NotificationModel.recipient_username == username))
            if row:
                row.status = "RESOLVED"
                row.read_at_utc = row.read_at_utc or datetime.now(timezone.utc).isoformat()

    def expire(self, username: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            statement = select(NotificationModel).where(NotificationModel.status.in_(("UNREAD", "READ")), NotificationModel.expires_at_utc.is_not(None), NotificationModel.expires_at_utc <= now)
            if username:
                statement = statement.where(NotificationModel.recipient_username == username)
            rows = session.scalars(statement).all()
            for row in rows:
                row.status = "EXPIRED"
            return len(rows)

    @staticmethod
    def _to_notification(row: NotificationModel) -> Notification:
        target_route = row.target_route
        # Repair notifications created by older builds before pending requests
        # were routed to the approval queue instead of Imports.
        if row.notification_type == "FILE_DETECTED" and "/requests/pending/" in row.entity_id:
            target_route = "/admin/approvals"
        return Notification(row.notification_id, row.recipient_username, row.notification_type, row.severity, row.title, row.message, target_route, row.status, row.entity_type, row.entity_id, row.created_at_utc, row.read_at_utc, row.expires_at_utc)
