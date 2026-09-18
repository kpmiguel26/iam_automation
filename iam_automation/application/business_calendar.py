"""
File: iam_automation/application/business_calendar.py
Purpose: User-configured calendar rules used by policy calculations.
Responsibilities: Loads the selected calendar/context and exposes business-day calculations.
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
from datetime import date
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
from ..domain.rules.calendar import CalendarConfigurationRequired, RuleCalendarSettings, business_days_between


def configured_rule_calendar(
    database_path: Path | None = None,
    context_version_id: str | None = None,
) -> RuleCalendarSettings:
    """Load the explicitly selected calendar and context version from SQLite.

    Rule evaluation is intentionally agnostic: missing configuration is an
    actionable user error, never an invitation to infer UTC, weekdays or
    holidays from process defaults.
    """
    if database_path is None or not Path(database_path).exists():
        raise CalendarConfigurationRequired(
            "No rule calendar is configured. Ask an administrator to configure and activate a calendar before evaluating rules."
        )

    try:
        with orm_session(Path(database_path)) as session:
            context = session.scalar(select(RuleContextModel).where(
                RuleContextModel.context_key == "DEFAULT",
                RuleContextModel.active.is_(True),
            ))
            context_version = session.get(RuleContextVersionModel, context_version_id) if context_version_id else None
            if context_version is None and context is not None:
                context_version = session.scalar(
                    select(RuleContextVersionModel).where(
                        RuleContextVersionModel.context_id == context.context_id,
                        RuleContextVersionModel.version == context.current_version,
                    )
                )
            if context_version is None:
                raise CalendarConfigurationRequired(
                    "No active rule-calendar context is configured. Ask an administrator to configure the calendar context before evaluating rules."
                )
            calendar_id = context_version.default_calendar_id
            if not calendar_id:
                raise CalendarConfigurationRequired(
                    "The active rule context has no selected calendar. Ask an administrator to select and save a calendar before evaluating rules."
                )
            calendar = session.get(RuleCalendarModel, calendar_id)
            if calendar is None:
                raise CalendarConfigurationRequired(
                    "The selected rule calendar is unavailable. Ask an administrator to configure and activate a valid calendar."
                )

            # New context versions carry the exact immutable calendar version.
            # The current-version lookup is retained only for pre-binding
            # databases/rows and is eliminated by migration 0021 for normal
            # runtime databases.
            version = None
            pinned_version_id = getattr(context_version, "default_calendar_version_id", None)
            if pinned_version_id:
                version = session.get(RuleCalendarVersionModel, pinned_version_id)
                if version is None or version.calendar_id != calendar.calendar_id:
                    raise CalendarConfigurationRequired(
                        "The selected rule calendar version is unavailable. Ask an administrator to save the calendar context again."
                    )
            else:
                raise CalendarConfigurationRequired(
                    "The rule context has no pinned calendar version. Ask an administrator to save the calendar context before evaluating rules."
                )
            if version is None:
                raise CalendarConfigurationRequired(
                    "The selected rule calendar has no configured version. Ask an administrator to save the calendar before evaluating rules."
                )
            try:
                weekdays = frozenset(int(item) for item in json.loads(version.operating_weekdays_json or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise CalendarConfigurationRequired(
                    "The selected rule calendar has invalid operating days. Ask an administrator to configure the calendar again."
                )
            if not weekdays or not weekdays.issubset(set(range(7))):
                raise CalendarConfigurationRequired(
                    "The selected rule calendar has invalid operating days. Ask an administrator to configure the calendar again."
                )
            timezone_name = str(version.timezone or "").strip()
            if not timezone_name:
                raise CalendarConfigurationRequired(
                    "The selected rule calendar has no timezone. Ask an administrator to configure the calendar again."
                )
            date_boundary = str(context_version.date_boundary or "").strip().upper()
            if date_boundary not in {"EXCLUSIVE_START_INCLUSIVE_END", "INCLUSIVE_BOTH"}:
                raise CalendarConfigurationRequired(
                    "The rule context has no valid date-boundary decision. Ask an administrator to configure the calendar context again."
                )

            holiday_rows = session.scalars(
                select(RuleCalendarHolidayModel).where(
                    RuleCalendarHolidayModel.calendar_version_id == version.calendar_version_id,
                    RuleCalendarHolidayModel.enabled.is_(True),
                )
            ).all()
            # Once the database has a configured calendar, it is the complete
            # source of truth. No process environment or host defaults are
            # merged into the selected version.
            exact: set[date] = set()
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
                timezone=timezone_name,
                date_boundary=date_boundary,
                operating_weekdays=weekdays,
                holiday_dates=frozenset(exact),
                recurring_holidays=frozenset(recurring),
            )
    except CalendarConfigurationRequired:
        raise
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        raise CalendarConfigurationRequired(
            "The rule calendar could not be loaded. Ask an administrator to verify and save the calendar configuration."
        ) from exc
#endfile
