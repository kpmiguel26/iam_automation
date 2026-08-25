"""
File: iam_automation/application/business_calendar.py
Purpose: Business-day rules used by policy calculations.
Responsibilities: Exposes or coordinates: configured_rehire_holidays, business_days_between.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import os
from datetime import date, timedelta


def configured_rehire_holidays() -> frozenset[date]:
    """Return configured rehire holidays without assuming an operating region.

    ``REHIRE_HOLIDAYS`` is an optional comma-separated list of ISO dates. Invalid
    entries are ignored so a malformed optional setting cannot stop ingestion.
    """
    holidays: set[date] = set()
    for value in os.getenv("REHIRE_HOLIDAYS", "").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            holidays.add(date.fromisoformat(value))
        except ValueError:
            continue
    return frozenset(holidays)


def business_days_between(start: date, end: date, holidays: frozenset[date] = frozenset()) -> int:
    """Count eligible business days after ``start`` through ``end``."""
    if end <= start:
        return 0 if end == start else -1
    current = start + timedelta(days=1)
    total = 0
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            total += 1
        current += timedelta(days=1)
    return total
#endfile
