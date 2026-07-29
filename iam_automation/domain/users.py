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
