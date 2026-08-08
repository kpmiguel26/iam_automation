"""
File: iam_automation/application/role_catalog.py
Purpose: Implements the application service for role catalog workflows.
Responsibilities: Exposes or coordinates: RoleOption.
Dependencies: identity
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..identity import ROLE_APPLICATION_ADMIN, ROLE_AUDITOR, ROLE_MASTER_ADMIN, ROLE_REQUESTER, ROLE_REVIEWER, ROLE_WRITER, ROLE_SUPER_OPERATOR


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
    RoleOption(ROLE_SUPER_OPERATOR, "Temporary Super Operator", "Temporary operational access; cannot publish Access or manage Master security.", admin_only=True),
)
