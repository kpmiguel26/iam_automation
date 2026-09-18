"""Pure calendar value objects and business-day calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


class CalendarConfigurationRequired(ValueError):
    """Raised when rule evaluation has no explicit user-configured calendar."""


@dataclass(frozen=True)
class RuleCalendarSettings:
    """Immutable calendar settings consumed by rule evaluation."""

    timezone: str
    date_boundary: str
    operating_weekdays: frozenset[int]
    holiday_dates: frozenset[date]
    recurring_holidays: frozenset[tuple[int, int]]

    def holidays_between(self, start: date, end: date) -> frozenset[date]:
        """Expand recurring holidays only for the dates being evaluated."""
        holidays = {item for item in self.holiday_dates if start <= item <= end}
        for month, day in self.recurring_holidays:
            for year in range(start.year, end.year + 1):
                try:
                    holiday = date(year, month, day)
                except ValueError:
                    continue
                if start <= holiday <= end:
                    holidays.add(holiday)
        return frozenset(holidays)


def business_days_between(
    start: date,
    end: date,
    holidays: frozenset[date],
    *,
    operating_weekdays: frozenset[int],
    start_inclusive: bool,
) -> int:
    """Count days using only the caller's explicit calendar decisions."""
    if end <= start:
        if end < start:
            return -1
        return 1 if start_inclusive and start.weekday() in operating_weekdays and start not in holidays else 0
    current = start if start_inclusive else start + timedelta(days=1)
    total = 0
    while current <= end:
        if current.weekday() in operating_weekdays and current not in holidays:
            total += 1
        current += timedelta(days=1)
    return total
