"""Canonical status vocabulary shared by source adapters and policies."""

from __future__ import annotations


ACCESSNOW_STATUS_ALIASES = {
    "TERM": "TERMINATED",
    "TERMINATED": "TERMINATED",
    "TERMINATION": "TERMINATED",
    "DEACT": "DEACTIVATED",
    "DEACTIVATED": "DEACTIVATED",
    "DEACTIVATION": "DEACTIVATED",
    "DISABLED": "DEACTIVATED",
    "INACTIVE": "DEACTIVATED",
    "ACTIVE": "ACTIVE",
}

CANONICAL_STATUS_RANK = {"ACTIVE": 1, "DEACTIVATED": 2, "TERMINATED": 3}


def normalize_accessnow_status(value: object) -> str:
    status = str(value or "").strip().upper()
    return ACCESSNOW_STATUS_ALIASES.get(status, status)


def status_rank(value: object) -> int:
    return CANONICAL_STATUS_RANK.get(normalize_accessnow_status(value), 0)


def is_inactive_source_status(value: object) -> bool:
    return normalize_accessnow_status(value) in {"TERMINATED", "DEACTIVATED"}
