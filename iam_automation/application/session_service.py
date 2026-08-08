"""
File: iam_automation/application/session_service.py
Purpose: Implements the application service for session service workflows.
Responsibilities: Exposes or coordinates: SessionRevocation, SessionService.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import SessionRevocationModel, orm_session


@dataclass(frozen=True)
class SessionRevocation:
    revocation_id: str
    username: str
    revoked_by: str
    revoked_at_utc: str
    reason: str


class SessionService:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def revoke_user(self, username: str, revoked_by: str, reason: str) -> SessionRevocation:
        if not username.strip() or not reason.strip():
            raise ValueError("Username and revocation reason are required.")
        item = SessionRevocation(str(uuid.uuid4()), username.strip(), revoked_by, datetime.now(timezone.utc).isoformat(), reason.strip())
        with orm_session(self.database_path) as session:
            session.add(SessionRevocationModel(revocation_id=item.revocation_id, username=item.username, revoked_by=item.revoked_by, revoked_at_utc=item.revoked_at_utc, reason=item.reason))
        return item

    def is_revoked(self, username: str, session_started_at: str) -> bool:
        with orm_session(self.database_path) as session:
            return session.scalar(select(SessionRevocationModel).where(SessionRevocationModel.username == username, SessionRevocationModel.revoked_at_utc >= session_started_at).limit(1)) is not None

    def list_recent(self, limit: int = 50) -> list[SessionRevocation]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(SessionRevocationModel).order_by(SessionRevocationModel.revoked_at_utc.desc()).limit(limit)).all()
            return [SessionRevocation(row.revocation_id, row.username, row.revoked_by, row.revoked_at_utc, row.reason) for row in rows]
