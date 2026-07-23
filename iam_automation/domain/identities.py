from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedIdentity:
    username: str
    display_name: str
    active: bool
    roles: tuple[str, ...]
