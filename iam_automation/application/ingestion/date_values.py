"""Shared date parsing rules for template previews and runtime ingestion."""

from __future__ import annotations

from datetime import date, datetime


def parse_date_value(value: str) -> date:
    """Parse supported date formats, reducing ISO date-times to their calendar date."""
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError("unsupported date format")
