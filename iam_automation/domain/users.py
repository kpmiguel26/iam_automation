from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationUser:
    username: str
    display_name: str
    active: bool
    roles: tuple[str, ...]
