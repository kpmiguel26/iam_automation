from __future__ import annotations

from pathlib import Path

from werkzeug.security import generate_password_hash

from ..domain.users import ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_INACTIVE, ACCOUNT_STATUSES, ApplicationUser
from ..identity import ROLE_APPLICATION_ADMIN, ROLE_AUDITOR, ROLE_MASTER_ADMIN, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_WRITER, normalize_role
from ..infrastructure.sqlite.user_repository import UserRepository


ALLOWED_ROLES = frozenset({ROLE_REQUESTER, ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_WRITER, ROLE_AUDITOR})
ADMINISTRATIVE_ROLES = frozenset({ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN})


class UserService:
    """Application use cases for local application-account administration."""

    def __init__(self, database_path: Path):
        self.repository = UserRepository(database_path)

    def list_users(self) -> list[ApplicationUser]:
        return self.repository.list_users()

    def get_user(self, username: str) -> ApplicationUser | None:
        """Load one account without scanning the complete user directory."""
        return self.repository.get_user(username)

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
        status: str | None = None,
    ) -> None:
        if not self.repository.get_user(username):
            raise ValueError(f"Application user was not found: {username}")
        password_hash = generate_password_hash(password) if password.strip() else None
        normalized_roles = self._roles(roles)
        normalized_status = self._status(status, active)
        current = self.repository.get_user(username)
        if current and current.active and normalized_status != ACCOUNT_STATUS_ACTIVE:
            if self._is_last_active_role(current.roles, ROLE_MASTER_ADMIN):
                raise ValueError("The last active administrator (MASTER_ADMIN) cannot be deactivated.")
            if self._is_last_active_admin(current.roles):
                raise ValueError("The last active administrator cannot be deactivated.")
        if current and self._is_last_active_role(current.roles, ROLE_MASTER_ADMIN) and ROLE_MASTER_ADMIN not in normalized_roles:
            raise ValueError("The last active administrator (MASTER_ADMIN) must retain MASTER_ADMIN access.")
        if current and self._is_last_active_admin(current.roles) and not (set(normalized_roles) & ADMINISTRATIVE_ROLES):
            raise ValueError("The last active administrator must retain an administrative role.")
        self.repository.update_user(
            username,
            display_name=display_name.strip(),
            roles=normalized_roles,
            active=normalized_status == ACCOUNT_STATUS_ACTIVE,
            status=normalized_status,
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
        normalized = tuple(sorted({normalize_role(role) for role in roles if role.strip()}))
        if not normalized or not set(normalized).issubset(ALLOWED_ROLES):
            raise ValueError(f"Roles must be selected from: {', '.join(sorted(ALLOWED_ROLES))}")
        return normalized

    @staticmethod
    def _status(status: str | None, active: bool) -> str:
        if not status:
            return ACCOUNT_STATUS_ACTIVE if active else ACCOUNT_STATUS_INACTIVE
        normalized = status.strip().upper()
        if normalized not in ACCOUNT_STATUSES:
            raise ValueError(f"Status must be selected from: {', '.join(sorted(ACCOUNT_STATUSES))}")
        return normalized

    def _is_last_active_admin(self, current_roles: tuple[str, ...]) -> bool:
        if not set(current_roles) & ADMINISTRATIVE_ROLES:
            return False
        return sum(1 for user in self.repository.list_users() if user.active and set(user.roles) & ADMINISTRATIVE_ROLES) == 1

    def _is_last_active_role(self, current_roles: tuple[str, ...], role: str) -> bool:
        if role not in set(current_roles):
            return False
        return sum(1 for user in self.repository.list_users() if user.active and role in set(user.roles)) == 1
