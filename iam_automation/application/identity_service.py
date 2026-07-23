from __future__ import annotations

from pathlib import Path

from ..domain.identities import ApprovedIdentity
from ..identity import ROLE_AUDITOR, ROLE_MASTER_ADMIN, normalize_role
from ..infrastructure.sqlite.identity_repository import ApprovedIdentityRepository


IDENTITY_ROLES = frozenset({"REQUESTER", "REVIEWER", "WRITER", "AUDITOR", "APPLICATION_ADMIN", "MASTER_ADMIN"})


class IdentityService:
    def __init__(self, database_path: Path):
        self.repository = ApprovedIdentityRepository(database_path)

    def list_identities(self) -> list[ApprovedIdentity]:
        return self.repository.list_identities()

    def save_identity(self, username: str, display_name: str, roles: list[str], active: bool, *, can_assign_master: bool) -> None:
        username = username.strip()
        if not username:
            raise ValueError("Windows username is required.")
        normalized = tuple(sorted({normalize_role(role) for role in roles if role.strip()})) or (ROLE_AUDITOR,)
        if not set(normalized).issubset(IDENTITY_ROLES):
            raise ValueError(f"Roles must be selected from: {', '.join(sorted(IDENTITY_ROLES))}")
        if ROLE_MASTER_ADMIN in normalized and not can_assign_master:
            raise PermissionError("Only MASTER_ADMIN can assign MASTER_ADMIN to a Windows identity.")
        self.repository.save(username, display_name.strip() or username, active, normalized)
