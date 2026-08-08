"""
File: iam_automation/application/source_date.py
Purpose: Date parsing helpers for source-system exports.
Responsibilities: Exposes or coordinates: parse_source_date.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import re
from datetime import date


_ISO_DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})")
_US_DATE_RE = re.compile(r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})")


def parse_source_date(value: object) -> date | None:
    """Parse ISO and AccessNow/Roster Lock date strings without timezone loss.

    The rehire policy uses calendar dates, so the timezone suffix on source
    timestamps is intentionally ignored after the date portion is extracted.
    """
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in (_ISO_DATE_RE, _US_DATE_RE):
        match = pattern.match(text)
        if not match:
            continue
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            return None
    return None
