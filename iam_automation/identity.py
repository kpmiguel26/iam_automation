"""
File: iam_automation/identity.py
Purpose: Provides the identity component of IAM Automation.
Responsibilities: Exposes or coordinates: normalize_role, CurrentUser, windows_username, computer_name, load_approved_users, validate_current_user, ….
Dependencies: getpass, socket
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import csv
import getpass
import os
import socket
from dataclasses import dataclass
from pathlib import Path

try:
    from werkzeug.security import check_password_hash
except ModuleNotFoundError:  # pragma: no cover - optional until Flask is installed
    check_password_hash = None  # type: ignore[assignment]


ROLE_REQUESTER = "REQUESTER"
ROLE_REVIEWER = "REVIEWER"
ROLE_ADMINISTRATOR = "ADMINISTRATOR"
ROLE_MASTER_ADMIN = "MASTER_ADMIN"
ROLE_APPLICATION_ADMIN = "APPLICATION_ADMIN"
ROLE_WRITER = "WRITER"
ROLE_AUDITOR = "AUDITOR"
ROLE_SUPER_OPERATOR = "SUPER_OPERATOR"

ROLE_ALIASES = {ROLE_ADMINISTRATOR: ROLE_APPLICATION_ADMIN}
ADMIN_ROLES = {ROLE_MASTER_ADMIN, ROLE_APPLICATION_ADMIN, ROLE_ADMINISTRATOR}
REQUEST_DECISION_ROLES = {ROLE_MASTER_ADMIN, ROLE_APPLICATION_ADMIN, ROLE_ADMINISTRATOR, ROLE_SUPER_OPERATOR}
WRITER_ROLES = {ROLE_APPLICATION_ADMIN, ROLE_ADMINISTRATOR, ROLE_WRITER, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}


def normalize_role(role: str) -> str:
    normalized = str(role).strip().upper()
    return ROLE_ALIASES.get(normalized, normalized)


@dataclass(frozen=True)
class CurrentUser:
    username: str
    computer: str
    roles: tuple[str, ...]

    @property
    def normalized_roles(self) -> tuple[str, ...]:
        return tuple(sorted({normalize_role(role) for role in self.roles}))

    @property
    def is_master_admin(self) -> bool:
        return ROLE_MASTER_ADMIN in self.normalized_roles

    @property
    def is_application_admin(self) -> bool:
        return bool({ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR} & set(self.normalized_roles))

    @property
    def is_writer(self) -> bool:
        return bool(set(self.normalized_roles) & {normalize_role(role) for role in WRITER_ROLES})

    @property
    def can_submit_requests(self) -> bool:
        return bool(set(self.normalized_roles) & {ROLE_REQUESTER, ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_WRITER, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR})

    @property
    def can_review_requests(self) -> bool:
        return bool(set(self.normalized_roles) & ({ROLE_REVIEWER} | REQUEST_DECISION_ROLES))

    @property
    def can_decide_requests(self) -> bool:
        """Only administrators can approve or reject; reviewers receive the work."""
        return bool(set(self.normalized_roles) & REQUEST_DECISION_ROLES)


def windows_username() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
    return f"{domain}\\{username}" if domain else username


def computer_name() -> str:
    return os.environ.get("COMPUTERNAME", "").strip() or socket.gethostname()


def load_approved_users(path: Path) -> dict[str, tuple[str, ...]]:
    if not path.exists():
        return {}
    users: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            username = str(row.get("username", "")).strip()
            active = str(row.get("active", "true")).strip().lower() in {"1", "true", "yes", "y"}
            if not username or not active:
                continue
            roles = tuple(
                item.strip()
                for item in str(row.get("roles", "")).replace(";", ",").split(",")
                if item.strip()
            )
            users[username.lower()] = tuple(normalize_role(role) for role in roles) or (ROLE_AUDITOR,)
    return users


def validate_current_user(approved_users_path: Path) -> CurrentUser:
    username = windows_username()
    users = load_approved_users(approved_users_path)
    roles = users.get(username.lower())
    if roles is None:
        raise PermissionError(f"Current user is not approved for IAM Automation: {username}")
    return CurrentUser(username=username, computer=computer_name(), roles=roles)


def load_approved_users_from_sqlite(path: Path) -> dict[str, tuple[str, ...]]:
    if not path.exists():
        return {}
    try:
        from sqlalchemy import select

        from .infrastructure.sqlite.orm import ApprovedUserModel, UserRoleModel, orm_session

        with orm_session(path) as session:
            active_users = {
                row.username.lower()
                for row in session.scalars(select(ApprovedUserModel).where(ApprovedUserModel.active.is_(True))).all()
            }
            rows = session.execute(select(UserRoleModel.username, UserRoleModel.role_name)).all()
    except Exception as exc:
        raise PermissionError(f"Runtime SQLite user validation failed: {path}: {exc}") from exc
    users: dict[str, set[str]] = {}
    for username, role in rows:
        normalized = str(username).strip().lower()
        if normalized in active_users:
            users.setdefault(normalized, set()).add(normalize_role(str(role)))
    return {username: tuple(sorted(roles)) for username, roles in users.items()}


def validate_current_user_from_sqlite(path: Path) -> CurrentUser:
    users = load_approved_users_from_sqlite(path)
    roles = users.get(windows_username().lower())
    if roles is None:
        raise PermissionError(f"Current user is not approved in runtime SQLite: {windows_username()}")
    return CurrentUser(username=windows_username(), computer=computer_name(), roles=roles)


def validate_app_user_from_sqlite(path: Path, username: str, password: str) -> CurrentUser:
    """Validate application credentials separately from the Windows identity gate."""
    if check_password_hash is None:
        raise PermissionError("Application password validation requires Werkzeug.")
    normalized = username.strip().lower()
    if not normalized or not password:
        raise PermissionError("Application username and password are required.")
    try:
        from sqlalchemy import func, select

        from .infrastructure.sqlite.orm import AppUserModel, orm_session

        with orm_session(path) as session:
            row = session.scalar(select(AppUserModel).where(func.lower(AppUserModel.username) == normalized, AppUserModel.status == "ACTIVE"))
            if not row:
                configured = session.scalar(select(AppUserModel.username).limit(1))
                if not configured:
                    raise PermissionError("No active application accounts are configured.")
                raise PermissionError("Invalid application username or password.")
            if not check_password_hash(str(row.password_hash), password):
                raise PermissionError("Invalid application username or password.")
            roles = tuple(normalize_role(item.role_name) for item in sorted(row.roles, key=lambda item: item.role_name)) or (ROLE_AUDITOR,)
            application_username = row.username
    except PermissionError:
        raise
    except Exception as exc:
        raise PermissionError(f"Application login database could not be read: {exc}") from exc
    from .application.temporary_super_operator_service import TemporarySuperOperatorService

    return CurrentUser(username=application_username, computer=computer_name(), roles=TemporarySuperOperatorService(path).effective_roles(application_username, roles))


def auto_approve_current_user_for_development(path: Path, role: str = ROLE_REQUESTER) -> CurrentUser:
    """Register the current OS identity for local development only."""
    username = windows_username()
    from sqlalchemy import select

    from .infrastructure.sqlite.orm import ApprovedUserModel, RoleModel, UserRoleModel, orm_session

    with orm_session(path) as session:
        approved = session.get(ApprovedUserModel, username)
        if approved is None:
            session.add(ApprovedUserModel(username=username, display_name=username, active=True))
        else:
            approved.active = True
        normalized_role = normalize_role(role)
        if session.get(RoleModel, normalized_role) is None:
            session.add(RoleModel(role_name=normalized_role, description="", active=True))
        if session.scalar(select(UserRoleModel).where(UserRoleModel.username == username, UserRoleModel.role_name == normalized_role)) is None:
            session.add(UserRoleModel(username=username, role_name=normalized_role))
    return validate_current_user_from_sqlite(path)
#endfile
