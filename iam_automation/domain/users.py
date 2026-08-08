"""
File: iam_automation/domain/users.py
Purpose: Defines domain models and rules for users.
Responsibilities: Exposes or coordinates: ApplicationUser.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from dataclasses import dataclass


ACCOUNT_STATUS_ACTIVE = "ACTIVE"
ACCOUNT_STATUS_SUSPENDED = "SUSPENDED"
ACCOUNT_STATUS_INACTIVE = "INACTIVE"
ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED = "PASSWORD_RESET_REQUIRED"
ACCOUNT_STATUSES = frozenset(
    {
        ACCOUNT_STATUS_ACTIVE,
        ACCOUNT_STATUS_SUSPENDED,
        ACCOUNT_STATUS_INACTIVE,
        ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED,
    }
)


@dataclass(frozen=True)
class ApplicationUser:
    username: str
    display_name: str
    active: bool
    roles: tuple[str, ...]
    status: str = ACCOUNT_STATUS_ACTIVE
