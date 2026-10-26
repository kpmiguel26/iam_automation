"""
File: iam_automation/infrastructure/sqlite/user_repository.py
Purpose: Provides SQLite persistence infrastructure for user repository.
Responsibilities: Exposes or coordinates: UserRepository.
Dependencies: sqlalchemy, domain, identity, orm
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select, update

from ...domain.users import ApplicationUser
from ...identity import normalize_role
from .orm import AppUserModel, UserRoleModel, orm_session


class UserRepository:
    """ORM persistence boundary for application users in runtime SQLite."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_users(self) -> list[ApplicationUser]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(AppUserModel).order_by(AppUserModel.username)).all()
            return [self._to_user(row) for row in rows]

    def get_user(self, username: str) -> ApplicationUser | None:
        with orm_session(self.database_path) as session:
            row = session.scalar(select(AppUserModel).where(AppUserModel.username == username))
            return self._to_user(row) if row else None

    def create_user(
        self,
        username: str,
        display_name: str,
        password_hash: str,
        roles: tuple[str, ...],
        *,
        active: bool = True,
        status: str = "ACTIVE",
    ) -> None:
        with orm_session(self.database_path) as session:
            user = AppUserModel(username=username, display_name=display_name, password_hash=password_hash, active=active, status=status)
            user.roles = [UserRoleModel(username=username, role_name=role) for role in roles]
            session.add(user)

    def update_user(
        self,
        username: str,
        *,
        display_name: str,
        roles: tuple[str, ...],
        active: bool,
        status: str = "ACTIVE",
        password_hash: str | None = None,
    ) -> None:
        with orm_session(self.database_path) as session:
            user = session.scalar(select(AppUserModel).where(AppUserModel.username == username))
            if user is None:
                raise ValueError(f"Application user was not found: {username}")
            user.display_name = display_name
            user.active = active
            user.status = status
            if password_hash:
                user.password_hash = password_hash
            session.execute(delete(UserRoleModel).where(UserRoleModel.username == username))
            user.roles = [UserRoleModel(username=username, role_name=role) for role in roles]

    def complete_initial_master_admin_setup(
        self,
        windows_username: str,
        application_username: str,
        *,
        display_name: str,
        password_hash: str,
        roles: tuple[str, ...],
    ) -> None:
        """Activate and optionally rename the staged first administrator atomically."""
        with orm_session(self.database_path) as session:
            session.execute(delete(UserRoleModel).where(UserRoleModel.username == windows_username))
            result = session.execute(
                update(AppUserModel)
                .where(AppUserModel.username == windows_username)
                .values(
                    username=application_username,
                    display_name=display_name,
                    password_hash=password_hash,
                    active=True,
                    status="ACTIVE",
                )
            )
            if result.rowcount != 1:
                raise ValueError("The staged first administrator account could not be found.")
            session.add_all(
                UserRoleModel(username=application_username, role_name=role)
                for role in roles
            )

    @staticmethod
    def _to_user(row: AppUserModel) -> ApplicationUser:
        roles = tuple(sorted(normalize_role(role.role_name) for role in row.roles))
        status = str(getattr(row, "status", "") or ("ACTIVE" if row.active else "INACTIVE")).upper()
        return ApplicationUser(row.username, row.display_name, status == "ACTIVE", roles, status)
#endfile
