from __future__ import annotations

import sqlite3
from pathlib import Path

from ...domain.users import ApplicationUser


class UserRepository:
    """Persistence boundary for application users in the local runtime SQLite."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list_users(self) -> list[ApplicationUser]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT u.username, u.display_name, u.active,
                       GROUP_CONCAT(ur.role_name, ',') AS roles
                FROM app_users u
                LEFT JOIN user_roles ur ON ur.username = u.username
                GROUP BY u.username, u.display_name, u.active
                ORDER BY lower(u.username)
                """
            ).fetchall()
        return [self._to_user(row) for row in rows]

    def get_user(self, username: str) -> ApplicationUser | None:
        return next((user for user in self.list_users() if user.username == username), None)

    def create_user(self, username: str, display_name: str, password_hash: str, roles: tuple[str, ...]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_users (username, display_name, password_hash) VALUES (?, ?, ?)",
                (username, display_name, password_hash),
            )
            self._replace_roles(connection, username, roles)
            connection.commit()

    def update_user(
        self,
        username: str,
        *,
        display_name: str,
        roles: tuple[str, ...],
        active: bool,
        password_hash: str | None = None,
    ) -> None:
        with self._connect() as connection:
            if password_hash:
                connection.execute(
                    "UPDATE app_users SET display_name = ?, active = ?, password_hash = ?, updated_at_utc = datetime('now') WHERE username = ?",
                    (display_name, int(active), password_hash, username),
                )
            else:
                connection.execute(
                    "UPDATE app_users SET display_name = ?, active = ?, updated_at_utc = datetime('now') WHERE username = ?",
                    (display_name, int(active), username),
                )
            self._replace_roles(connection, username, roles)
            connection.commit()

    @staticmethod
    def _replace_roles(connection: sqlite3.Connection, username: str, roles: tuple[str, ...]) -> None:
        connection.execute("DELETE FROM user_roles WHERE username = ?", (username,))
        connection.executemany(
            "INSERT INTO user_roles (username, role_name) VALUES (?, ?)",
            [(username, role) for role in roles],
        )

    @staticmethod
    def _to_user(row: sqlite3.Row) -> ApplicationUser:
        roles = tuple(sorted(role for role in str(row["roles"] or "").split(",") if role))
        return ApplicationUser(str(row["username"]), str(row["display_name"]), bool(row["active"]), roles)
