"""
File: iam_automation/application/notification_service.py
Purpose: Implements the application service for notification service workflows.
Responsibilities: Exposes or coordinates: Notification, NotificationService.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, insert, select

from ..infrastructure.sqlite.orm import AppUserModel, NotificationModel, UserRoleModel, orm_session
from .shared_notification_store import SharedNotificationStore


REHIRE_NOTIFICATION_LOCK = threading.RLock()


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
    def __init__(self, database_path: Path, *, sharepoint_root: Path | None = None):
        self.database_path = database_path
        self.shared_store = SharedNotificationStore(sharepoint_root) if sharepoint_root else None

    def unread_count(self, username: str) -> int:
        self.expire(username)
        shared_count = len(self.shared_store.list_for_user(username, unread_only=True)) if self.shared_store else 0
        with orm_session(self.database_path) as session:
            local_count = int(session.scalar(select(func.count(NotificationModel.notification_id)).where(
                NotificationModel.recipient_username == username,
                NotificationModel.status == "UNREAD",
            )) or 0)
        return local_count + shared_count

    def list_for_user(self, username: str, *, unread_only: bool = False) -> list[Notification]:
        self.expire(username)
        statement = select(NotificationModel).where(NotificationModel.recipient_username == username).order_by(NotificationModel.created_at_utc.desc())
        if unread_only:
            statement = statement.where(NotificationModel.status == "UNREAD")
        with orm_session(self.database_path) as session:
            local_items = [self._to_notification(row) for row in session.scalars(statement).all()]
        shared_records = self.shared_store.list_for_user(username) if self.shared_store else []
        shared_items = [
            self._from_shared_notification(item)
            for item in shared_records
            if not unread_only or str(item.get("status")) == "UNREAD"
        ]
        shared_event_keys = {
            (str(item.get("notification_type", "")), str(item.get("entity_type", "")), str(item.get("entity_id", "")))
            for item in shared_records
        }
        local_items = [
            item for item in local_items
            if (item.notification_type, item.entity_type, item.entity_id) not in shared_event_keys
        ]
        existing_ids = {item.notification_id for item in local_items}
        return sorted(local_items + [item for item in shared_items if item.notification_id not in existing_ids], key=lambda item: item.created_at_utc, reverse=True)

    def mark_all_read(self, username: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(NotificationModel).where(NotificationModel.recipient_username == username, NotificationModel.status == "UNREAD")).all()
            for row in rows:
                row.status = "READ"
                row.read_at_utc = now
            local_count = len(rows)
        return local_count + (self.shared_store.mark_all_read(username) if self.shared_store else 0)

    def create(self, recipient_username: str, notification_type: str, title: str, message: str, *, severity: str = "INFO", target_route: str = "", entity_type: str = "", entity_id: str = "", expires_at_utc: str | None = None, notification_id: str | None = None) -> str:
        notification_id = str(notification_id or uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        if self.shared_store:
            self.shared_store.publish(
                notification_id=notification_id,
                notification_type=notification_type,
                title=title,
                message=message,
                recipients=[recipient_username],
                severity=severity,
                target_route=target_route,
                entity_type=entity_type,
                entity_id=entity_id,
                created_at_utc=created_at,
                expires_at_utc=expires_at_utc,
            )
            return notification_id
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
                created_at_utc=created_at,
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
            if self.shared_store:
                notification_id = hashlib.sha256(f"request-review-event:{request_id}".encode("utf-8")).hexdigest()
                self.shared_store.publish(
                    notification_id=notification_id,
                    notification_type="REQUEST_REVIEW_REQUIRED",
                    severity="WARNING",
                    title="Request ready for review",
                    message=message,
                    recipients=recipients,
                    entity_type="change_request",
                    entity_id=request_id,
                    target_route="/admin/approvals",
                    created_at_utc=now,
                )
                return len(recipients)
            for username in recipients:
                notification_id = hashlib.sha256(
                    f"request-review:{username.lower()}:{request_id}".encode("utf-8")
                ).hexdigest()
                existing = session.get(NotificationModel, notification_id)
                if existing is None:
                    session.add(NotificationModel(
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
                else:
                    # Re-publishing the same shared request must not reset a
                    # user's READ/RESOLVED decision back to UNREAD.
                    existing.message = message
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
            if self.shared_store:
                notification_id = hashlib.sha256(f"source-update-event:{request_id}".encode("utf-8")).hexdigest()
                self.shared_store.publish(
                    notification_id=notification_id,
                    notification_type="SOURCE_UPDATE_AVAILABLE",
                    severity="WARNING",
                    title="Source update ready for individual review",
                    message=(
                        f"{record_count} source record(s) from {operation_type.replace('_', ' ').title()} "
                        "are waiting in Employee Updates. No employee was created automatically."
                    ),
                    recipients=recipients,
                    entity_type="change_request",
                    entity_id=request_id,
                    target_route="/employees/source-updates",
                    created_at_utc=now,
                )
                return len(recipients)
            for username in recipients:
                notification_id = hashlib.sha256(
                    f"source-update:{username.lower()}:{request_id}".encode("utf-8")
                ).hexdigest()
                message = (
                    f"{record_count} source record(s) from {operation_type.replace('_', ' ').title()} "
                    "are waiting in Employee Updates. No employee was created automatically."
                )
                existing = session.get(NotificationModel, notification_id)
                if existing is None:
                    session.add(NotificationModel(
                        notification_id=notification_id,
                        recipient_username=username,
                        notification_type="SOURCE_UPDATE_AVAILABLE",
                        severity="WARNING",
                        title="Source update ready for individual review",
                        message=message,
                        entity_type="change_request",
                        entity_id=request_id,
                        target_route="/employees/source-updates",
                        status="UNREAD",
                        created_at_utc=now,
                    ))
                else:
                    existing.message = message
            return len(recipients)

    def notify_rehire_alerts(self, alerts: list[dict[str, object]]) -> int:
        if self.shared_store:
            return self._notify_shared_rehire_alerts(alerts)
        with REHIRE_NOTIFICATION_LOCK:
            return self._notify_rehire_alerts(alerts)

    def _notify_shared_rehire_alerts(self, alerts: list[dict[str, object]]) -> int:
        role_names = ("REVIEWER", "APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        unique_alerts = {str(alert["alert_id"]): alert for alert in alerts}
        active_event_ids = {
            hashlib.sha256(f"rehire-alert-event:{alert_id}".encode("utf-8")).hexdigest()
            for alert_id in unique_alerts
        }
        self.shared_store.deactivate_type_except("REHIRE_30_DAY_ALERT", active_event_ids)
        with orm_session(self.database_path) as session:
            recipients = {row.username for row in session.scalars(
                select(AppUserModel).join(UserRoleModel).where(
                    AppUserModel.active.is_(True),
                    AppUserModel.status == "ACTIVE",
                    UserRoleModel.role_name.in_(role_names),
                )
            ).all()}
        created = 0
        for alert_id, alert in unique_alerts.items():
            remaining = int(alert.get("business_days_remaining", 0))
            notification_id = hashlib.sha256(f"rehire-alert-event:{alert_id}".encode("utf-8")).hexdigest()
            created += int(self.shared_store.publish(
                notification_id=notification_id,
                notification_type="REHIRE_30_DAY_ALERT",
                severity="CRITICAL",
                title="Critical 30-day rehire alert",
                message=(
                    f"{alert.get('worker_name', 'Employee')} appears in Roster Lock while AccessNow shows "
                    f"{str(alert.get('status', 'TERMINATED')).lower()}. The 30-business-day rehire hold "
                    f"has not elapsed ({remaining} business day(s) remaining)."
                ),
                recipients=recipients,
                entity_type="ingestion_record",
                entity_id=alert_id,
                target_route="/employees/source-updates",
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                active=True,
            ))
        return created

    def _notify_rehire_alerts(self, alerts: list[dict[str, object]]) -> int:
        """Reconcile critical rehire notifications with the current alert set."""
        role_names = ("REVIEWER", "APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR", "ADMINISTRATOR")
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        unique_alerts: dict[str, dict[str, object]] = {}
        for alert in alerts:
            unique_alerts[str(alert["alert_id"])] = alert
        alerts = list(unique_alerts.values())
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
                    result = session.execute(insert(NotificationModel).prefix_with("OR IGNORE").values(
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
                    created += int(result.rowcount or 0)
        return created

    def mark_read(self, username: str, notification_id: str) -> None:
        if self.shared_store and self.shared_store.mark_read(notification_id, username):
            return
        with orm_session(self.database_path) as session:
            row = session.scalar(select(NotificationModel).where(
                NotificationModel.notification_id == notification_id,
                NotificationModel.recipient_username == username,
            ))
            if row:
                row.status = "READ"
                row.read_at_utc = datetime.now(timezone.utc).isoformat()

    def resolve(self, username: str, notification_id: str) -> None:
        if self.shared_store and self.shared_store.resolve(notification_id, username):
            return
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
#endfile
