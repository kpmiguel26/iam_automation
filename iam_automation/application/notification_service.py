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


class NotificationService:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def unread_count(self, username: str) -> int:
        with orm_session(self.database_path) as session:
            return int(session.scalar(select(func.count(NotificationModel.notification_id)).where(
                NotificationModel.recipient_username == username,
                NotificationModel.status == "UNREAD",
            )) or 0)

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[Notification]:
        statement = select(NotificationModel).where(NotificationModel.recipient_username == username).order_by(NotificationModel.created_at_utc.desc())
        if unread_only:
            statement = statement.where(NotificationModel.status == "UNREAD")
        with orm_session(self.database_path) as session:
            return [self._to_notification(row) for row in session.scalars(statement).all()]

    def create(self, recipient_username: str, notification_type: str, title: str, message: str, *, severity: str = "INFO", target_route: str = "") -> str:
        notification_id = str(uuid.uuid4())
        with orm_session(self.database_path) as session:
            session.add(NotificationModel(
                notification_id=notification_id,
                recipient_username=recipient_username,
                notification_type=notification_type,
                severity=severity,
                title=title,
                message=message,
                target_route=target_route,
                status="UNREAD",
                created_at_utc=datetime.now(timezone.utc).isoformat(),
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

    @staticmethod
    def _to_notification(row: NotificationModel) -> Notification:
        return Notification(row.notification_id, row.recipient_username, row.notification_type, row.severity, row.title, row.message, row.target_route, row.status)
