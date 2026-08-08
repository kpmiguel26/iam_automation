"""
File: iam_automation/application/identity_service.py
Purpose: Implements the application service for identity service workflows.
Responsibilities: Exposes or coordinates: IdentityService.
Dependencies: domain, identity, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

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

    def save_identity(self, username: str, display_name: str, roles: list[str] | None, active: bool, *, can_assign_master: bool = False) -> None:
        username = username.strip()
        if not username:
            raise ValueError("Windows username is required.")
        self.repository.save(username, display_name.strip() or username, active, ())
