from __future__ import annotations

import csv
import getpass
import os
import socket
import sqlite3
from dataclasses import dataclass
from pathlib import Path


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
