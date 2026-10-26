"""
File: iam_automation/application/user_service.py
Purpose: Implements the application service for user service workflows.
Responsibilities: Exposes or coordinates: UserService.
Dependencies: werkzeug, domain, identity, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from ..domain.users import ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_INACTIVE, ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED, ACCOUNT_STATUSES, ApplicationUser
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

    def ensure_initial_master_admin(self, windows_username: str) -> bool:
        """Stage a one-time MASTER_ADMIN for the current OS identity if none is active."""
        username = self._required(windows_username, "Windows username")
        users = self.repository.list_users()
        if any(user.active and set(user.roles) & ADMINISTRATIVE_ROLES for user in users):
            return False

        password_hash = generate_password_hash(secrets.token_urlsafe(48))
        existing = next((user for user in users if user.username.lower() == username.lower()), None)
        if existing:
            self.repository.update_user(
                existing.username,
                display_name=existing.display_name or username,
                roles=tuple(sorted(set(existing.roles) | {ROLE_MASTER_ADMIN})),
                active=False,
                status=ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED,
                password_hash=password_hash,
            )
        else:
            self.repository.create_user(
                username,
                username,
                password_hash,
                (ROLE_MASTER_ADMIN,),
                active=False,
                status=ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED,
            )
        return True

    def initial_master_admin_setup_pending(self, windows_username: str) -> bool:
        username = windows_username.strip().lower()
        if not username:
            return False
        users = self.repository.list_users()
        if any(user.active and set(user.roles) & ADMINISTRATIVE_ROLES for user in users):
            return False
        return any(
            user.username.lower() == username
            and user.status == ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED
            and ROLE_MASTER_ADMIN in user.roles
            for user in users
        )

    def initial_master_admin_setup_available(self, windows_username: str) -> bool:
        """Allow the current Windows account to finish or rename its bootstrap admin once."""
        username = windows_username.strip().lower()
        if not username:
            return False
        if self.initial_master_admin_setup_pending(username):
            return True
        active_admins = [
            user for user in self.repository.list_users()
            if user.active and set(user.roles) & ADMINISTRATIVE_ROLES
        ]
        return (
            len(active_admins) == 1
            and active_admins[0].username.lower() == username
            and ROLE_MASTER_ADMIN in active_admins[0].roles
        )

    def complete_initial_master_admin_setup(
        self,
        windows_username: str,
        application_username: str,
        display_name: str,
        password: str,
    ) -> None:
        windows_username = self._required(windows_username, "Windows username")
        application_username = self._required(application_username, "Application username")
        display_name = self._required(display_name, "Administrator name")
        if application_username.lower() == windows_username.lower():
            raise ValueError("Choose an application username separate from your Windows username.")
        if len(password) < 12:
            raise ValueError("Choose a password with at least 12 characters.")
        if not self.initial_master_admin_setup_available(windows_username):
            raise ValueError("First administrator setup is no longer available for this Windows user.")
        users = self.repository.list_users()
        user = next(user for user in users if user.username.lower() == windows_username.lower())
        if any(
            existing.username.lower() == application_username.lower()
            and existing.username.lower() != windows_username.lower()
            for existing in users
        ):
            raise ValueError("That application username is already in use.")
        roles = tuple(sorted(set(user.roles) | {ROLE_MASTER_ADMIN}))
        self.repository.complete_initial_master_admin_setup(
            user.username,
            application_username,
            display_name=display_name,
            roles=roles,
            password_hash=generate_password_hash(password),
        )

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
#endfile
