"""
File: iam_automation/application/publication_service.py
Purpose: Implements the application service for publication service workflows.
Responsibilities: Exposes or coordinates: PublicationItem, PublicationService.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import PublicationQueueModel, orm_session


@dataclass(frozen=True)
class PublicationItem:
    publication_id: str
    request_id: str
    status: str
    queued_by: str
    queued_at_utc: str
    error_message: str | None


class PublicationService:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_pending(self) -> list[PublicationItem]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(PublicationQueueModel).where(PublicationQueueModel.status == "PENDING_PUBLICATION").order_by(PublicationQueueModel.queued_at_utc)).all()
            return [self._to_item(row) for row in rows]

    def enqueue(self, request_id: str, queued_by: str) -> PublicationItem:
        with orm_session(self.database_path) as session:
            row = session.scalar(select(PublicationQueueModel).where(PublicationQueueModel.request_id == request_id))
            if row is None:
                row = PublicationQueueModel(publication_id=__import__("uuid").uuid4().hex, request_id=request_id, status="PENDING_PUBLICATION", queued_by=queued_by, queued_at_utc=datetime.now(timezone.utc).isoformat())
                session.add(row)
            return self._to_item(row)

    @staticmethod
    def _to_item(row: PublicationQueueModel) -> PublicationItem:
        return PublicationItem(row.publication_id, row.request_id, row.status, row.queued_by, row.queued_at_utc, row.error_message)
