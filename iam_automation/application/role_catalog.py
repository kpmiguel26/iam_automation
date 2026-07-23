from __future__ import annotations

from dataclasses import dataclass

from ..identity import ROLE_APPLICATION_ADMIN, ROLE_AUDITOR, ROLE_MASTER_ADMIN, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_WRITER


@dataclass(frozen=True)
class RoleOption:
    value: str
    label: str
    description: str
    admin_only: bool = False


ROLE_OPTIONS = (
    RoleOption(ROLE_REQUESTER, "Requester", "Creates and tracks IAM requests."),
    RoleOption(ROLE_REVIEWER, "Reviewer", "Reviews and decides requests."),
    RoleOption(ROLE_WRITER, "Writer", "Applies approved changes and publishes."),
    RoleOption(ROLE_AUDITOR, "Auditor", "Reads and exports evidence."),
    RoleOption(ROLE_APPLICATION_ADMIN, "Application Administrator", "Operates users, approvals and data workflows."),
    RoleOption(ROLE_MASTER_ADMIN, "Master Administrator", "Controls security, recovery and global settings.", admin_only=True),
)
