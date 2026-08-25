"""
File: iam_automation/domain/users.py
Purpose: Defines domain models and rules for users.
Responsibilities: Exposes or coordinates: ApplicationUser.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
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
#endfile
