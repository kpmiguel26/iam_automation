from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import ChangeRequestModel, DelegationModel, ImportBatchModel, NotificationModel, PublicationQueueModel, QuarantineRecordModel, orm_session


class OverviewService:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def snapshot(self, username: str) -> dict:
        if not self.database_path.exists():
            return {
                "requests": {status: 0 for status in ("PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED")},
                "total_requests": 0,
                "open_quarantine": 0,
                "pending_publication": 0,
                "active_delegations": 0,
                "unread_notifications": 0,
                "import_batches": 0,
            }
        with orm_session(self.database_path) as session:
            request_counts = {
                status: int(session.scalar(select(func.count(ChangeRequestModel.request_id)).where(ChangeRequestModel.status == status)) or 0)
                for status in ("PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED")
            }
            return {
                "requests": request_counts,
                "total_requests": sum(request_counts.values()),
                "open_quarantine": int(session.scalar(select(func.count(QuarantineRecordModel.quarantine_id)).where(QuarantineRecordModel.status == "OPEN")) or 0),
                "pending_publication": int(session.scalar(select(func.count(PublicationQueueModel.publication_id)).where(PublicationQueueModel.status == "PENDING_PUBLICATION")) or 0),
                "active_delegations": int(session.scalar(select(func.count(DelegationModel.delegation_id)).where(DelegationModel.status == "ACTIVE")) or 0),
                "unread_notifications": int(session.scalar(select(func.count(NotificationModel.notification_id)).where(NotificationModel.recipient_username == username, NotificationModel.status == "UNREAD")) or 0),
                "import_batches": int(session.scalar(select(func.count(ImportBatchModel.batch_id))) or 0),
            }
