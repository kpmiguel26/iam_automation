"""Manage the local, versioned context used by advisory business rules."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..holiday_provider import fetch_public_holidays
from ...infrastructure.sqlite.orm import (
    DimFieldModel,
    DimSourceModel,
    RuleCalendarHolidayModel,
    RuleCalendarModel,
    RuleCalendarVersionModel,
    RuleContextModel,
    RuleContextVersionModel,
    SourceFieldMappingModel,
    orm_session,
)


class RuleConfigurationService:
    """Application service for rule context and field metadata.

    This service only changes local rule metadata. It never changes source
    evidence, canonical employees or source-to-field mappings.
    """

    DATA_TYPES = ("TEXT", "NUMBER", "DATE", "DATETIME", "BOOLEAN", "IDENTIFIER", "ENUM")
    NORMALIZATIONS = ("identity", "trim", "casefold", "parse_date", "parse_number")
    MISSING_DATA_BEHAVIORS = ("SKIP", "FINDING", "NOT_APPLICABLE")
    DATE_BOUNDARIES = ("EXCLUSIVE_START_INCLUSIVE_END", "INCLUSIVE_BOTH")
    DEFAULT_OPERATORS = {
        "TEXT": ("exists", "missing", "equals", "not_equals", "contains", "in"),
        "IDENTIFIER": ("exists", "missing", "equals", "not_equals", "contains", "in"),
        "ENUM": ("exists", "missing", "equals", "not_equals", "in"),
        "NUMBER": ("exists", "missing", "equals", "not_equals", "greater_than", "less_than", "between"),
        "DATE": ("exists", "missing", "equals", "before", "after", "between"),
        "DATETIME": ("exists", "missing", "equals", "before", "after", "between"),
        "BOOLEAN": ("exists", "missing", "equals", "not_equals"),
    }

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: str, fallback):
        try:
            parsed = json.loads(value or "")
            return parsed
        except (TypeError, ValueError):
            return fallback

    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 80 or any(char.isspace() for char in value):
            raise ValueError("Use a valid IANA time zone, for example UTC or America/Guatemala.")
        return value

    @classmethod
    def _validate_weekdays(cls, values) -> list[int]:
        try:
            weekdays = sorted({int(value) for value in values})
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose at least one operating day.") from exc
        if not weekdays or any(value < 0 or value > 6 for value in weekdays):
            raise ValueError("Choose valid operating days from Monday through Sunday.")
        return weekdays

    @classmethod
    def _parse_holidays(cls, value: str) -> list[dict[str, object]]:
        holidays: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for line in str(value or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|", 2)]
            try:
                holiday_date = date.fromisoformat(parts[0])
            except (IndexError, ValueError) as exc:
                raise ValueError(f"Invalid holiday '{line}'. Use YYYY-MM-DD|Label.") from exc
            label = parts[1] if len(parts) > 1 else ""
            recurring = len(parts) > 2 and parts[2].casefold() in {"1", "true", "yes", "y"}
            key = (holiday_date.isoformat(), label.casefold())
            if key in seen:
                continue
            seen.add(key)
            holidays.append({"date": holiday_date.isoformat(), "label": label, "recurring": recurring})
        return holidays

    def _current_calendar(self, session, calendar_id: str | None = None) -> tuple[RuleCalendarModel, RuleCalendarVersionModel]:
        calendar = session.get(RuleCalendarModel, calendar_id) if calendar_id else session.scalar(
            select(RuleCalendarModel).where(RuleCalendarModel.active.is_(True)).order_by(RuleCalendarModel.calendar_key.asc())
        )
        if calendar is None:
            raise ValueError("No active rule calendar is configured.")
        version = session.scalar(
            select(RuleCalendarVersionModel).where(
                RuleCalendarVersionModel.calendar_id == calendar.calendar_id,
                RuleCalendarVersionModel.version == calendar.current_version,
            )
        )
        if version is None:
            raise ValueError("The selected calendar has no current version.")
        return calendar, version

    def configuration(self) -> dict:
        with orm_session(self.database_path) as session:
            context = session.scalar(select(RuleContextModel).where(RuleContextModel.context_key == "DEFAULT"))
            context_version = None
            if context is not None:
                context_version = session.scalar(
                    select(RuleContextVersionModel).where(
                        RuleContextVersionModel.context_id == context.context_id,
                        RuleContextVersionModel.version == context.current_version,
                    )
                )
            calendars = session.scalars(select(RuleCalendarModel).where(RuleCalendarModel.active.is_(True)).order_by(RuleCalendarModel.label.asc())).all()
            calendar_data = []
            for calendar in calendars:
                _, version = self._current_calendar(session, calendar.calendar_id)
                holidays = session.scalars(
                    select(RuleCalendarHolidayModel).where(RuleCalendarHolidayModel.calendar_version_id == version.calendar_version_id).order_by(RuleCalendarHolidayModel.holiday_date.asc())
                ).all()
                calendar_data.append({
                    "model": calendar,
                    "version": version,
                    "weekdays": self._json(version.operating_weekdays_json, []),
                    "holidays": holidays,
                })
            fields = self._field_data(session)
            return {
                "context": context,
                "context_version": context_version,
                "calendars": calendar_data,
                "fields": fields,
                "data_types": self.DATA_TYPES,
                "normalizations": self.NORMALIZATIONS,
                "missing_data_behaviors": self.MISSING_DATA_BEHAVIORS,
                "date_boundaries": self.DATE_BOUNDARIES,
            }

    @staticmethod
    def _field_data(session) -> list[dict]:
        fields = session.scalars(select(DimFieldModel).where(DimFieldModel.active.is_(True)).order_by(DimFieldModel.field_key.asc())).all()
        sources = {source.source_id: source.label or source.source_system for source in session.scalars(select(DimSourceModel)).all()}
        mappings = session.scalars(select(SourceFieldMappingModel).where(SourceFieldMappingModel.active.is_(True))).all()
        source_by_field: dict[str, set[str]] = {}
        for mapping in mappings:
            if mapping.field_id in {field.field_id for field in fields}:
                source_by_field.setdefault(mapping.field_id, set()).add(sources.get(mapping.source_id, mapping.source_id))
        result = []
        for field in fields:
            data_type = str(field.data_type or field.semantic_type or "TEXT").upper()
            semantic_type = str(field.semantic_type or data_type).upper()
            operators = RuleConfigurationService._json(field.allowed_operators_json, [])
            if not isinstance(operators, list) or not operators:
                operators = list(RuleConfigurationService.DEFAULT_OPERATORS.get(semantic_type, RuleConfigurationService.DEFAULT_OPERATORS["TEXT"]))
            result.append({
                "model": field,
                "data_type": data_type if data_type in RuleConfigurationService.DATA_TYPES else "TEXT",
                "semantic_type": semantic_type if semantic_type in RuleConfigurationService.DATA_TYPES else "TEXT",
                "operators": operators,
                "sources": sorted(source_by_field.get(field.field_id, set())) or ["Governed field"],
            })
        return result

    def save_context(self, *, calendar_id: str, timezone_name: str, missing_data_behavior: str, date_boundary: str, actor: str) -> dict:
        timezone_name = self._validate_timezone(timezone_name)
        missing_data_behavior = str(missing_data_behavior or "").upper()
        date_boundary = str(date_boundary or "").upper()
        if missing_data_behavior not in self.MISSING_DATA_BEHAVIORS:
            raise ValueError("Choose a valid missing-data behavior.")
        if date_boundary not in self.DATE_BOUNDARIES:
            raise ValueError("Choose a valid date boundary.")
        now = self._now()
        with orm_session(self.database_path) as session:
            calendar, calendar_version = self._current_calendar(session, calendar_id)
            context = session.scalar(select(RuleContextModel).where(RuleContextModel.context_key == "DEFAULT"))
            if context is None:
                context = RuleContextModel(context_id="context:default", context_key="DEFAULT", label="Default rule context", current_version=0, active=True, created_by=actor, created_at_utc=now, updated_at_utc=now)
                session.add(context)
                session.flush()
            version_number = int(context.current_version or 0) + 1
            version = RuleContextVersionModel(
                context_version_id=f"{context.context_id}:{version_number}", context_id=context.context_id, version=version_number,
                default_calendar_id=calendar.calendar_id, default_calendar_version_id=calendar_version.calendar_version_id,
                timezone=timezone_name, missing_data_behavior=missing_data_behavior,
                date_boundary=date_boundary, created_by=actor, created_at_utc=now,
            )
            session.add(version)
            context.current_version = version_number
            context.updated_at_utc = now
            return {"version": version_number}

    def save_calendar(self, *, calendar_id: str, label: str, timezone_name: str, weekdays, holidays: str, actor: str, holiday_rows: list[dict] | None = None) -> dict:
        label = str(label or "").strip()
        if not label:
            raise ValueError("Calendar name is required.")
        timezone_name = self._validate_timezone(timezone_name)
        weekdays = self._validate_weekdays(weekdays)
        parsed_holidays: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for item in holiday_rows or []:
            try:
                holiday_date = date.fromisoformat(str(item.get("date") or ""))
            except (TypeError, ValueError) as exc:
                raise ValueError("Holiday dates must use YYYY-MM-DD.") from exc
            label_value = str(item.get("label") or "").strip()
            key = (holiday_date.isoformat(), label_value.casefold())
            if key in seen:
                continue
            seen.add(key)
            source_year = item.get("year")
            if source_year not in (None, ""):
                try:
                    source_year = int(source_year)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Holiday source years must be valid numbers.") from exc
            parsed_holidays.append({
                "date": holiday_date.isoformat(), "label": label_value,
                "recurring": bool(item.get("recurring")), "enabled": bool(item.get("enabled", True)),
                "source": str(item.get("source") or "MANUAL"), "country": str(item.get("country") or ""),
                "year": source_year, "type": str(item.get("type") or ""),
                "observed_date": str(item.get("observed_date") or holiday_date.isoformat()),
            })
        for item in self._parse_holidays(holidays):
            key = (str(item["date"]), str(item["label"]).casefold())
            if key not in seen:
                seen.add(key)
                parsed_holidays.append(item)
        now = self._now()
        with orm_session(self.database_path) as session:
            calendar, current = self._current_calendar(session, calendar_id or None)
            version_number = int(calendar.current_version or 0) + 1
            calendar.label = label
            calendar.current_version = version_number
            calendar.updated_at_utc = now
            version = RuleCalendarVersionModel(
                calendar_version_id=f"{calendar.calendar_id}:{version_number}:{uuid.uuid4().hex[:8]}", calendar_id=calendar.calendar_id,
                version=version_number, timezone=timezone_name, operating_weekdays_json=json.dumps(weekdays), created_by=actor, created_at_utc=now,
            )
            session.add(version)
            session.flush()
            for holiday in parsed_holidays:
                session.add(RuleCalendarHolidayModel(
                    holiday_id=str(uuid.uuid4()), calendar_version_id=version.calendar_version_id,
                    holiday_date=str(holiday["date"]), label=str(holiday["label"]), recurring_annually=bool(holiday.get("recurring")),
                    enabled=bool(holiday.get("enabled", True)), source=str(holiday.get("source") or "MANUAL"),
                    source_country=str(holiday.get("country") or ""), source_year=holiday.get("year"),
                    holiday_type=str(holiday.get("type") or ""), observed_date=str(holiday.get("observed_date") or holiday["date"]),
                ))
            return {"calendar_id": calendar.calendar_id, "version": version_number, "previous_version": current.version}

    def import_holidays(self, *, calendar_id: str, country_code: str, year: int, actor: str) -> dict:
        country_code = str(country_code or "").strip().upper()
        try:
            year = int(year)
        except (TypeError, ValueError) as exc:
            raise ValueError("Year must be a valid number.") from exc
        imported = fetch_public_holidays(country_code, year)
        now = self._now()
        with orm_session(self.database_path) as session:
            calendar, current = self._current_calendar(session, calendar_id)
            existing = session.scalars(
                select(RuleCalendarHolidayModel).where(RuleCalendarHolidayModel.calendar_version_id == current.calendar_version_id)
            ).all()
            rows: list[dict[str, object]] = [{
                "date": item.holiday_date, "label": item.label, "recurring": item.recurring_annually,
                "enabled": item.enabled, "source": item.source, "country": item.source_country,
                "year": item.source_year, "type": item.holiday_type, "observed_date": item.observed_date,
            } for item in existing]
            keys = {(str(item["date"]), str(item["label"]).casefold()) for item in rows}
            added = 0
            for item in imported:
                key = (str(item["date"]), str(item["label"]).casefold())
                if key in keys:
                    continue
                rows.append(item)
                keys.add(key)
                added += 1
            version_number = int(calendar.current_version or 0) + 1
            version = RuleCalendarVersionModel(
                calendar_version_id=f"{calendar.calendar_id}:{version_number}:{uuid.uuid4().hex[:8]}", calendar_id=calendar.calendar_id,
                version=version_number, timezone=current.timezone, operating_weekdays_json=current.operating_weekdays_json,
                created_by=actor, created_at_utc=now,
            )
            session.add(version)
            session.flush()
            calendar.current_version = version_number
            calendar.updated_at_utc = now
            for item in rows:
                session.add(RuleCalendarHolidayModel(
                    holiday_id=str(uuid.uuid4()), calendar_version_id=version.calendar_version_id,
                    holiday_date=str(item["date"]), label=str(item["label"]), recurring_annually=bool(item.get("recurring")),
                    enabled=bool(item.get("enabled", True)), source=str(item.get("source") or "MANUAL"),
                    source_country=str(item.get("country") or ""), source_year=item.get("year"),
                    holiday_type=str(item.get("type") or ""), observed_date=str(item.get("observed_date") or item["date"]),
                ))
            return {"calendar_id": calendar.calendar_id, "version": version_number, "imported": len(imported), "added": added, "country": str(country_code).upper(), "year": int(year)}

    def update_field(self, *, field_id: str, data_type: str, nullable: bool, rule_enabled: bool, normalization_name: str, actor: str) -> dict:
        data_type = str(data_type or "").upper()
        normalization_name = str(normalization_name or "identity").strip()
        if data_type not in self.DATA_TYPES:
            raise ValueError("Choose a valid field data type.")
        if normalization_name not in self.NORMALIZATIONS:
            raise ValueError("Choose a valid field normalization.")
        now = self._now()
        with orm_session(self.database_path) as session:
            field = session.get(DimFieldModel, field_id)
            if field is None or not field.active:
                raise ValueError("Field not found.")
            field.data_type = data_type
            field.semantic_type = data_type
            field.nullable = bool(nullable)
            field.rule_enabled = bool(rule_enabled)
            field.normalization_name = normalization_name
            field.allowed_operators_json = json.dumps(self.DEFAULT_OPERATORS[data_type])
            field.metadata_version = int(field.metadata_version or 0) + 1
            field.updated_by = actor
            field.updated_at_utc = now
            return {"field_key": field.field_key, "version": field.metadata_version}
