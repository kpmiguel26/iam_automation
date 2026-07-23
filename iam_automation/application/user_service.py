from __future__ import annotations

from pathlib import Path

from werkzeug.security import generate_password_hash

from ..domain.users import ApplicationUser
from ..identity import ROLE_ADMINISTRATOR, ROLE_AUDITOR, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_WRITER
from ..infrastructure.sqlite.user_repository import UserRepository


ALLOWED_ROLES = frozenset({ROLE_REQUESTER, ROLE_REVIEWER, ROLE_ADMINISTRATOR, ROLE_WRITER, ROLE_AUDITOR})


class UserService:
    """Application use cases for local application-account administration."""

    def __init__(self, database_path: Path):
        self.repository = UserRepository(database_path)

    def list_users(self) -> list[ApplicationUser]:
        return self.repository.list_users()

    def create_user(self, username: str, display_name: str, password: str, roles: list[str]) -> None:
        username = self._required(username, "Username")
        password = self._required(password, "Password")
        normalized_roles = self._roles(roles)
        if self.repository.get_user(username):
            raise ValueError(f"Application user already exists: {username}")
        self.repository.create_user(username, display_name.strip(), generate_password_hash(password), normalized_roles)

    def update_user(
        self,
        username: str,
        *,
        display_name: str,
        password: str,
        roles: list[str],
        active: bool,
    ) -> None:
        if not self.repository.get_user(username):
            raise ValueError(f"Application user was not found: {username}")
        password_hash = generate_password_hash(password) if password.strip() else None
        self.repository.update_user(
            username,
            display_name=display_name.strip(),
            roles=self._roles(roles),
            active=active,
            password_hash=password_hash,
        )

    @staticmethod
    def _required(value: str, label: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{label} is required.")
        return value

    @staticmethod
    def _roles(roles: list[str]) -> tuple[str, ...]:
        normalized = tuple(sorted({role.strip().upper() for role in roles if role.strip()}))
        if not normalized or not set(normalized).issubset(ALLOWED_ROLES):
            raise ValueError(f"Roles must be selected from: {', '.join(sorted(ALLOWED_ROLES))}")
        return normalized
