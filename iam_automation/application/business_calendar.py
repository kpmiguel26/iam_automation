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

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..infrastructure.sqlite.orm import (
    RuleCalendarHolidayModel,
    RuleCalendarModel,
    RuleCalendarVersionModel,
    RuleContextModel,
    RuleContextVersionModel,
    orm_session,
)


@dataclass(frozen=True)
class RuleCalendarSettings:
    """Immutable calendar settings consumed by rule evaluation."""

    timezone: str = "UTC"
    date_boundary: str = "EXCLUSIVE_START_INCLUSIVE_END"
    operating_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    holiday_dates: frozenset[date] = frozenset()
    recurring_holidays: frozenset[tuple[int, int]] = frozenset()

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


def configured_rule_calendar(
    database_path: Path | None = None,
    context_version_id: str | None = None,
) -> RuleCalendarSettings:
    """Load the active local rule calendar, preserving the legacy env setting.

    The environment variable remains a compatibility fallback for installations
    that have not yet created the configuration tables. Database holidays are
    local metadata only; no source evidence is changed by this lookup.
    """
    fallback_holidays = configured_rehire_holidays()
    default = RuleCalendarSettings(holiday_dates=fallback_holidays)
    if database_path is None or not Path(database_path).exists():
        return default

    try:
        with orm_session(Path(database_path)) as session:
            context = session.scalar(select(RuleContextModel).where(
                RuleContextModel.context_key == "DEFAULT",
                RuleContextModel.active.is_(True),
            ))
            calendar_id = None
            context_version = session.get(RuleContextVersionModel, context_version_id) if context_version_id else None
            if context_version is None and context is not None:
                context_version = session.scalar(
                    select(RuleContextVersionModel).where(
                        RuleContextVersionModel.context_id == context.context_id,
                        RuleContextVersionModel.version == context.current_version,
                    )
                )
            calendar_id = context_version.default_calendar_id if context_version is not None else None
            calendar = session.get(RuleCalendarModel, calendar_id) if calendar_id else session.scalar(
                select(RuleCalendarModel).where(RuleCalendarModel.active.is_(True)).order_by(RuleCalendarModel.calendar_key.asc())
            )
            if calendar is None:
                return default
            version = session.scalar(
                select(RuleCalendarVersionModel).where(
                    RuleCalendarVersionModel.calendar_id == calendar.calendar_id,
                    RuleCalendarVersionModel.version == calendar.current_version,
                )
            )
            if version is None:
                return default
            try:
                weekdays = frozenset(int(item) for item in json.loads(version.operating_weekdays_json or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                weekdays = default.operating_weekdays
            if not weekdays or not weekdays.issubset(set(range(7))):
                weekdays = default.operating_weekdays

            holiday_rows = session.scalars(
                select(RuleCalendarHolidayModel).where(
                    RuleCalendarHolidayModel.calendar_version_id == version.calendar_version_id,
                    RuleCalendarHolidayModel.enabled.is_(True),
                )
            ).all()
            exact: set[date] = set(fallback_holidays)
            recurring: set[tuple[int, int]] = set()
            for holiday in holiday_rows:
                try:
                    holiday_date = date.fromisoformat(str(holiday.holiday_date))
                except (TypeError, ValueError):
                    continue
                if holiday.recurring_annually:
                    recurring.add((holiday_date.month, holiday_date.day))
                else:
                    exact.add(holiday_date)
                if holiday.observed_date:
                    try:
                        exact.add(date.fromisoformat(str(holiday.observed_date)))
                    except ValueError:
                        pass
            return RuleCalendarSettings(
                timezone=str(version.timezone or "UTC"),
                date_boundary=str(context_version.date_boundary if context_version is not None else default.date_boundary),
                operating_weekdays=weekdays,
                holiday_dates=frozenset(exact),
                recurring_holidays=frozenset(recurring),
            )
    except (OSError, RuntimeError, SQLAlchemyError):
        # A rule evaluation must remain available on a legacy database. The
        # configured env fallback is deterministic and keeps old deployments
        # working while migrations are applied.
        return default


def business_days_between(
    start: date,
    end: date,
    holidays: frozenset[date] = frozenset(),
    *,
    operating_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4}),
    start_inclusive: bool = False,
) -> int:
    """Count eligible business days after ``start`` through ``end``."""
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
#endfile
