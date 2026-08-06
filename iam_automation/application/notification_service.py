from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import AppUserModel, NotificationModel, UserRoleModel, orm_session


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

    def notify_request_reviewers(
        self,
        request_id: str,
        operation_type: str,
        created_by: str,
        *,
        record_count: int = 0,
    ) -> int:
        """Publish one idempotent review notification to every eligible user.

        Reviewers are allowed to inspect the request, while administrators are
        the decision makers.  The notification is intentionally local because
        the request itself is the shared SharePoint JSON connector.
        """
        role_names = ("REVIEWER", "APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        now = datetime.now(timezone.utc).isoformat()
        message = (
            f"{operation_type.replace('_', ' ').title()} request {request_id[:8]} "
            f"is ready for review ({record_count} record(s)). Submitted by {created_by}."
        )
        recipients: set[str] = set()
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
            recipients = {row.username for row in rows}
            for username in recipients:
                notification_id = hashlib.sha256(
                    f"request-review:{username.lower()}:{request_id}".encode("utf-8")
                ).hexdigest()
                session.merge(NotificationModel(
                    notification_id=notification_id,
                    recipient_username=username,
                    notification_type="REQUEST_REVIEW_REQUIRED",
                    severity="WARNING",
                    title="Request ready for review",
                    message=message,
                    entity_type="change_request",
                    entity_id=request_id,
                    target_route="/admin/approvals",
                    status="UNREAD",
                    created_at_utc=now,
                ))
        return len(recipients)

    def notify_source_update_available(self, request_id: str, operation_type: str, record_count: int) -> int:
        """Notify administrators that approved source data awaits row review."""
        role_names = ("APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            rows = session.scalars(
                select(AppUserModel).join(UserRoleModel).where(
                    AppUserModel.active.is_(True),
                    AppUserModel.status == "ACTIVE",
                    UserRoleModel.role_name.in_(role_names),
                )
            ).all()
            recipients = {row.username for row in rows}
            for username in recipients:
                notification_id = hashlib.sha256(
                    f"source-update:{username.lower()}:{request_id}".encode("utf-8")
                ).hexdigest()
                session.merge(NotificationModel(
                    notification_id=notification_id,
                    recipient_username=username,
                    notification_type="SOURCE_UPDATE_AVAILABLE",
                    severity="WARNING",
                    title="Source update ready for individual review",
                    message=(
                        f"{record_count} source record(s) from {operation_type.replace('_', ' ').title()} "
                        "are waiting in Employee Updates. No employee was created automatically."
                    ),
                    entity_type="change_request",
                    entity_id=request_id,
                    target_route="/employees/source-updates",
                    status="UNREAD",
                    created_at_utc=now,
                ))
            return len(recipients)

    def notify_rehire_alerts(self, alerts: list[dict[str, object]]) -> int:
        """Reconcile critical rehire notifications with the current alert set."""
        role_names = ("REVIEWER", "APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            active_alert_ids = {str(alert["alert_id"]) for alert in alerts}
            stale = session.scalars(select(NotificationModel).where(
                NotificationModel.notification_type == "REHIRE_30_DAY_ALERT",
                NotificationModel.status.in_(("UNREAD", "READ")),
            )).all()
            for notification in stale:
                if notification.entity_id not in active_alert_ids:
                    notification.status = "EXPIRED"
                    notification.read_at_utc = notification.read_at_utc or now
            if not alerts:
                return 0
            recipients = {row.username for row in session.scalars(
                select(AppUserModel).join(UserRoleModel).where(
                    AppUserModel.active.is_(True),
                    AppUserModel.status == "ACTIVE",
                    UserRoleModel.role_name.in_(role_names),
                )
            ).all()}
            for alert in alerts:
                alert_id = str(alert["alert_id"])
                remaining = int(alert.get("business_days_remaining", 0))
                for username in recipients:
                    notification_id = hashlib.sha256(f"rehire-alert:{username.lower()}:{alert_id}".encode("utf-8")).hexdigest()
                    existing = session.get(NotificationModel, notification_id)
                    if existing is not None and existing.status == "EXPIRED":
                        existing.status = "UNREAD"
                        existing.read_at_utc = None
                        existing.expires_at_utc = None
                        existing.message = (
                            f"{alert.get('worker_name', 'Employee')} appears in Roster Lock while AccessNow shows "
                            f"{str(alert.get('status', 'TERMINATED')).lower()}. The 30-business-day rehire hold "
                            f"has not elapsed ({remaining} business day(s) remaining)."
                        )
                    elif existing is not None:
                        continue
                    session.add(NotificationModel(
                        notification_id=notification_id,
                        recipient_username=username,
                        notification_type="REHIRE_30_DAY_ALERT",
                        severity="CRITICAL",
                        title="Critical 30-day rehire alert",
                        message=(
                            f"{alert.get('worker_name', 'Employee')} appears in Roster Lock while AccessNow shows "
                            f"{str(alert.get('status', 'TERMINATED')).lower()}. The 30-business-day rehire hold "
                            f"has not elapsed ({remaining} business day(s) remaining)."
                        ),
                        entity_type="ingestion_record",
                        entity_id=alert_id,
                        target_route="/employees/source-updates",
                        status="UNREAD",
                        created_at_utc=now,
                    ))
                    created += 1
        return created

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
