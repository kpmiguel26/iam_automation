from __future__ import annotations

import csv
import getpass
import os
import socket
import sqlite3
from dataclasses import dataclass
from pathlib import Path

try:
    from werkzeug.security import check_password_hash
except ModuleNotFoundError:  # pragma: no cover - optional until Flask is installed
    check_password_hash = None  # type: ignore[assignment]


ROLE_REQUESTER = "REQUESTER"
ROLE_REVIEWER = "REVIEWER"
ROLE_ADMINISTRATOR = "ADMINISTRATOR"
ROLE_WRITER = "WRITER"
ROLE_AUDITOR = "AUDITOR"

WRITER_ROLES = {ROLE_ADMINISTRATOR, ROLE_WRITER}


@dataclass(frozen=True)
class CurrentUser:
    username: str
    computer: str
    roles: tuple[str, ...]

    @property
    def is_writer(self) -> bool:
        return any(role.upper() in WRITER_ROLES for role in self.roles)

    @property
    def can_submit_requests(self) -> bool:
        return any(role.upper() in {ROLE_REQUESTER, ROLE_REVIEWER, ROLE_ADMINISTRATOR, ROLE_WRITER} for role in self.roles)

    @property
    def can_review_requests(self) -> bool:
        return any(role.upper() in {ROLE_REVIEWER, ROLE_ADMINISTRATOR, ROLE_WRITER} for role in self.roles)


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
            users[username.lower()] = tuple(role.upper() for role in roles) or (ROLE_AUDITOR,)
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
    users: dict[str, set[str]] = {}
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT username, role_name FROM user_roles"
            ).fetchall()
            active_users = {
                str(row[0]).lower()
                for row in connection.execute("SELECT username FROM approved_users WHERE active = 1").fetchall()
            }
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {}
        raise PermissionError(f"Runtime SQLite user validation failed: {path}: {exc}") from exc
    except sqlite3.Error as exc:
        raise PermissionError(f"Runtime SQLite user validation failed: {path}: {exc}") from exc
    for username, role in rows:
        normalized = str(username).strip().lower()
        if normalized in active_users:
            users.setdefault(normalized, set()).add(str(role).strip().upper())
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
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT username, password_hash FROM app_users WHERE lower(username) = ? AND active = 1",
                (normalized,),
            ).fetchone()
            if not row:
                configured = connection.execute("SELECT 1 FROM app_users WHERE active = 1 LIMIT 1").fetchone()
                if not configured:
                    raise PermissionError("No active application accounts are configured.")
                raise PermissionError("Invalid application username or password.")
            if not check_password_hash(str(row[1]), password):
                raise PermissionError("Invalid application username or password.")
            roles = tuple(
                str(item[0]).strip().upper()
                for item in connection.execute(
                    "SELECT role_name FROM user_roles WHERE username = ? ORDER BY role_name",
                    (row[0],),
                ).fetchall()
                if str(item[0]).strip()
            ) or (ROLE_AUDITOR,)
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            raise PermissionError("Application users are not configured in runtime SQLite.") from exc
        raise PermissionError(f"Application login database could not be read: {exc}") from exc
    except sqlite3.Error as exc:
        raise PermissionError(f"Application login database could not be read: {exc}") from exc
    return CurrentUser(username=str(row[0]), computer=computer_name(), roles=roles)


def auto_approve_current_user_for_development(path: Path, role: str = ROLE_REQUESTER) -> CurrentUser:
    """Register the current OS identity for local development only."""
    username = windows_username()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO approved_users (username, display_name, active) VALUES (?, ?, 1) "
            "ON CONFLICT(username) DO UPDATE SET active = 1",
            (username, username),
        )
        connection.execute(
            "INSERT INTO roles (role_name, description, active) VALUES (?, '', 1) "
            "ON CONFLICT(role_name) DO UPDATE SET active = 1",
            (role.upper(),),
        )
        connection.execute(
            "INSERT OR IGNORE INTO user_roles (username, role_name) VALUES (?, ?)",
            (username, role.upper()),
        )
        connection.commit()
    finally:
        connection.close()
    return validate_current_user_from_sqlite(path)
