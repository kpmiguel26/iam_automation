from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import DelegationModel, orm_session


@dataclass(frozen=True)
class Delegation:
    delegation_id: str
    principal_username: str
    delegate_username: str
    scope: str
    starts_at_utc: str
    expires_at_utc: str
    reason: str
    status: str


class DelegationService:
    ALLOWED_SCOPES = frozenset({"APPROVALS", "INGESTION", "PUBLICATION", "FULL_OPERATIONS"})

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_active(self) -> list[Delegation]:
        self.expire_due()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(DelegationModel).where(DelegationModel.status == "ACTIVE").order_by(DelegationModel.expires_at_utc)).all()
            for row in rows:
                if row.expires_at_utc <= now:
                    row.status = "EXPIRED"
            return [self._to_delegation(row) for row in rows if row.status == "ACTIVE"]

    def list_all(self) -> list[Delegation]:
        self.expire_due()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(DelegationModel).order_by(DelegationModel.expires_at_utc.desc())).all()
            return [self._to_delegation(row) for row in rows]

    def expire_due(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(DelegationModel).where(DelegationModel.status == "ACTIVE", DelegationModel.expires_at_utc <= now)).all()
            for row in rows:
                row.status = "EXPIRED"
            return len(rows)

    def create(self, principal: str, delegate: str, scope: str, starts_at_utc: str, expires_at_utc: str, reason: str, created_by: str) -> Delegation:
        scope = scope.strip().upper()
        if scope not in self.ALLOWED_SCOPES:
            raise ValueError(f"Unsupported delegation scope: {scope}")
        if delegate.strip().lower() == principal.strip().lower():
            raise ValueError("An administrator cannot delegate to themselves.")
        if not reason.strip():
            raise ValueError("Delegation reason is required.")
        if expires_at_utc <= starts_at_utc:
            raise ValueError("Delegation expiration must be after its start.")
        delegation = Delegation(str(uuid.uuid4()), principal, delegate, scope, starts_at_utc, expires_at_utc, reason.strip(), "ACTIVE")
        with orm_session(self.database_path) as session:
            session.add(DelegationModel(
                delegation_id=delegation.delegation_id,
                principal_username=principal,
                delegate_username=delegate,
                scope=scope,
                starts_at_utc=starts_at_utc,
                expires_at_utc=expires_at_utc,
                reason=delegation.reason,
                status="ACTIVE",
                created_by=created_by,
                created_at_utc=datetime.now(timezone.utc).isoformat(),
            ))
        return delegation

    def revoke(self, delegation_id: str) -> None:
        with orm_session(self.database_path) as session:
            row = session.scalar(select(DelegationModel).where(DelegationModel.delegation_id == delegation_id, DelegationModel.status == "ACTIVE"))
            if row:
                row.status = "REVOKED"
                row.revoked_at_utc = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_delegation(row: DelegationModel) -> Delegation:
        return Delegation(row.delegation_id, row.principal_username, row.delegate_username, row.scope, row.starts_at_utc, row.expires_at_utc, row.reason, row.status)
