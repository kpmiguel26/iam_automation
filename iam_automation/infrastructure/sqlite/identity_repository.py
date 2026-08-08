"""
File: iam_automation/infrastructure/sqlite/identity_repository.py
Purpose: Provides SQLite persistence infrastructure for identity repository.
Responsibilities: Exposes or coordinates: ApprovedIdentityRepository.
Dependencies: sqlalchemy, domain, identity, orm
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from ...domain.identities import ApprovedIdentity
from ...identity import normalize_role
from .orm import ApprovedUserModel, UserRoleModel, orm_session


class ApprovedIdentityRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_identities(self) -> list[ApprovedIdentity]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(ApprovedUserModel).order_by(ApprovedUserModel.username)).all()
            return [self._to_identity(session, row) for row in rows]

    def get_identity(self, username: str) -> ApprovedIdentity | None:
        with orm_session(self.database_path) as session:
            row = session.get(ApprovedUserModel, username)
            return self._to_identity(session, row) if row else None

    def save(self, username: str, display_name: str, active: bool, roles: tuple[str, ...]) -> None:
        with orm_session(self.database_path) as session:
            row = session.get(ApprovedUserModel, username)
            if row is None:
                session.add(ApprovedUserModel(username=username, display_name=display_name, active=active))
            else:
                row.display_name = display_name
                row.active = active
            session.execute(delete(UserRoleModel).where(UserRoleModel.username == username))
            session.add_all([UserRoleModel(username=username, role_name=role) for role in roles])

    @staticmethod
    def _to_identity(session, row: ApprovedUserModel) -> ApprovedIdentity:
        roles = tuple(sorted(normalize_role(item.role_name) for item in session.scalars(select(UserRoleModel).where(UserRoleModel.username == row.username)).all()))
        return ApprovedIdentity(row.username, row.display_name, bool(row.active), roles)
