"""
File: iam_automation/application/report_service.py
Purpose: Implements the application service for report service workflows.
Responsibilities: Exposes or coordinates: ReportField, ReportStudioResult, VendorReportRow, NewHireReadinessRow, ReportSnapshot, ReportService.
Dependencies: sqlalchemy, infrastructure
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..infrastructure.sqlite.orm import (
    WorkerDiscrepancyModel,
    WorkerEngagementModel,
    IngestionRecordModel,
    WorkerModel,
    WorkerSourceProfileModel,
    orm_session,
)
from .source_date import parse_source_date


@dataclass(frozen=True)
class ReportField:
    key: str
    label: str
    source: str
    data_type: str
    filterable: bool = True
    sortable: bool = True
    groupable: bool = False
    sensitive: bool = False


@dataclass(frozen=True)
class ReportStudioResult:
    fields: tuple[ReportField, ...]
    rows: tuple[dict[str, Any], ...]
    total_rows: int
    definition: dict[str, Any]
    filter_options: dict[str, tuple[str, ...]]


REPORT_SOURCES: tuple[tuple[str, str], ...] = (
    ("ALL", "All canonical data"),
    ("CANONICAL", "Canonical employees"),
    ("ROSTER_LOCK", "Master Roster Lock"),
    ("RSR_SUPPLIER_WORKER_DETAILS", "Fieldglass / RSR"),
    ("ACCESSNOW", "AccessNow"),
)

REPORT_FIELDS: tuple[ReportField, ...] = (
    ReportField("employee.display_name", "Employee", "Canonical", "text", groupable=True),
    ReportField("employee.email", "Email", "Canonical", "text", sensitive=True),
    ReportField("employee.worker_id", "Worker ID", "Canonical", "text"),
    ReportField("employee.status", "Employee status", "Canonical", "status", groupable=True),
    ReportField("engagement.vendor_name", "Vendor", "Engagement", "text", groupable=True),
    ReportField("engagement.project", "Project", "Engagement", "text", groupable=True),
    ReportField("engagement.supervisor_name", "Supervisor", "Engagement", "text", groupable=True),
    ReportField("engagement.job_title", "Job title", "Engagement", "text", groupable=True),
    ReportField("engagement.onboarding_date", "Work start date", "Engagement", "date"),
    ReportField("engagement.production_start_date", "Production start date", "Engagement", "date"),
    ReportField("engagement.statement_of_work", "Statement of work", "Engagement", "text"),
    ReportField("engagement.work_order_id", "Work order", "Engagement", "text"),
    ReportField("source.source_system", "Source", "Lineage", "text", groupable=True),
    ReportField("coverage.roster_lock", "Master Roster Lock coverage", "Coverage", "boolean", groupable=True),
    ReportField("coverage.fieldglass", "Fieldglass / RSR coverage", "Coverage", "boolean", groupable=True),
    ReportField("coverage.accessnow", "AccessNow coverage", "Coverage", "boolean", groupable=True),
    ReportField("quality.open_discrepancies", "Open discrepancies", "Quality", "number"),
)

REPORT_FIELDS_BY_KEY = {field.key: field for field in REPORT_FIELDS}
REPORT_SOURCES_BY_KEY = dict(REPORT_SOURCES)
SOURCE_DISPLAY_NAMES = {key: label for key, label in REPORT_SOURCES if key not in {"ALL", "CANONICAL"}}

# Fields that do not originate in every source file are limited to the files
# where the normalized ingestion model can provide a meaningful value.
REPORT_FIELD_SOURCES: dict[str, set[str]] = {
    "engagement.vendor_name": {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"},
    "engagement.project": {"ROSTER_LOCK"},
    "engagement.supervisor_name": {"ROSTER_LOCK"},
    "engagement.job_title": {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"},
    "engagement.onboarding_date": {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"},
    "engagement.production_start_date": {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"},
    "engagement.statement_of_work": {"RSR_SUPPLIER_WORKER_DETAILS"},
    "engagement.work_order_id": {"RSR_SUPPLIER_WORKER_DETAILS"},
}


@dataclass(frozen=True)
class VendorReportRow:
    vendor_name: str
    employee_count: int
    engagement_count: int
    active_count: int
    pending_inactive_count: int
    open_discrepancy_count: int


@dataclass(frozen=True)
class NewHireReadinessRow:
    worker_id: str
    display_name: str
    email: str
    vendor_name: str
    roster_lock_role: str
    fieldglass_job_title: str
    work_start_date: str
    status: str
    accessnow_terminated_date: str
    fieldglass_present: bool
    accessnow_present: bool

    @property
    def missing_fieldglass(self) -> bool:
        return not self.fieldglass_present

    @property
    def missing_accessnow(self) -> bool:
        return not self.accessnow_present


@dataclass(frozen=True)
class TerminationReportRow:
    worker_id: str
    employee_id: str
    display_name: str
    email: str
    termination_date: str
    vendor_name: str
    roster_lock_role: str
    fieldglass_job_title: str
    work_start_date: str


@dataclass(frozen=True)
class TerminationBreakdownRow:
    label: str
    terminations: int
    population_exposed: int

    @property
    def attrition_rate(self) -> float:
        return (self.terminations / self.population_exposed * 100) if self.population_exposed else 0.0


@dataclass(frozen=True)
class TerminationReport:
    start_date: str
    end_date: str
    total_terminations: int
    population_exposed: int
    rows: tuple[TerminationReportRow, ...]
    by_role: tuple[TerminationBreakdownRow, ...]
    by_vendor: tuple[TerminationBreakdownRow, ...]
    by_month: tuple[tuple[str, int], ...]

    @property
    def attrition_rate(self) -> float:
        return (self.total_terminations / self.population_exposed * 100) if self.population_exposed else 0.0


@dataclass(frozen=True)
class ReportSnapshot:
    total_employees: int
    active_employees: int
    pending_inactive_employees: int
    total_vendors: int
    employees_without_vendor: int
    open_discrepancies: int
    total_vendor_engagements: int
    as_of_utc: str
    vendors: tuple[VendorReportRow, ...]


class ReportService:
    """Build read-only workforce reports from the canonical SQLite runtime."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _raw_field_key(source: str, field_name: str) -> str:
        return f"raw.{source}.{field_name}"

    @staticmethod
    def _raw_field_parts(field_key: str) -> tuple[str, str] | None:
        if not field_key.startswith("raw."):
            return None
        _, source, field_name = field_key.split(".", 2)
        return source, field_name

    @staticmethod
    def _display_field_name(field_name: str) -> str:
        return field_name.replace("_", " ").replace("-", " ").strip().title()

    @staticmethod
    def _infer_data_type(field_name: str, values: list[str]) -> str:
        name = field_name.casefold()
        if any(token in name for token in ("date", "start", "end", "created", "updated", "termination")):
            return "date"
        if values and all(value.casefold() in {"true", "false", "yes", "no"} for value in values):
            return "boolean"
        if values:
            try:
                [float(value.replace(",", "")) for value in values]
                return "number"
            except ValueError:
                pass
        return "text"

    def _raw_fields(self, source: str) -> tuple[ReportField, ...]:
        if not self.database_path.exists() or source == "CANONICAL":
            return ()
        allowed_sources = set(SOURCE_DISPLAY_NAMES) if source == "ALL" else {source}
        values_by_key: dict[tuple[str, str], list[str]] = {}
        with orm_session(self.database_path) as session:
            profiles = session.scalars(select(WorkerSourceProfileModel)).all()
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status == "APPLIED")).all()
        payloads = [(profile.source_system, profile.snapshot_json) for profile in profiles]
        payloads.extend((record.source_system, record.payload_json or record.normalized_json) for record in records)
        for source_system, payload_json in payloads:
            source_system = str(source_system or "").upper()
            if source_system not in allowed_sources:
                continue
            try:
                payload = json.loads(payload_json or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for field_name, value in payload.items():
                field_name = str(field_name or "").strip()
                if not field_name:
                    continue
                text = "" if value is None else str(value).strip()
                values_by_key.setdefault((source_system, field_name), []).append(text)
        return tuple(
            ReportField(
                self._raw_field_key(source_system, field_name),
                self._display_field_name(field_name),
                SOURCE_DISPLAY_NAMES.get(source_system, source_system),
                self._infer_data_type(field_name, [value for value in values if value]),
                sensitive=any(token in field_name.casefold() for token in ("email", "nuid", "employee_id", "worker_id")),
            )
            for (source_system, field_name), values in sorted(values_by_key.items(), key=lambda item: (item[0][0], item[0][1].casefold()))
        )

    def field_catalog(self, source: str = "ALL") -> tuple[ReportField, ...]:
        source = source if source in REPORT_SOURCES_BY_KEY else "ALL"
        if source in {"ALL", "CANONICAL"}:
            static_fields = REPORT_FIELDS
        else:
            static_fields = tuple(field for field in REPORT_FIELDS if field.key not in REPORT_FIELD_SOURCES or source in REPORT_FIELD_SOURCES[field.key])
        return static_fields + self._raw_fields(source)

    @staticmethod
    def source_catalog() -> tuple[tuple[str, str], ...]:
        return REPORT_SOURCES

    def field_groups(self, source: str = "ALL", fields: tuple[ReportField, ...] | None = None) -> tuple[tuple[str, tuple[ReportField, ...]], ...]:
        """Return the visible catalog grouped by the source that supplies it."""
        fields = fields if fields is not None else self.field_catalog(source)
        groups: list[tuple[str, tuple[ReportField, ...]]] = []
        canonical = tuple(field for field in fields if field.key.startswith("employee."))
        if canonical:
            groups.append(("Canonical employee fields", canonical))

        source_groups = (
            ("Master Roster Lock", "ROSTER_LOCK"),
            ("Fieldglass / RSR", "RSR_SUPPLIER_WORKER_DETAILS"),
            ("AccessNow", "ACCESSNOW"),
        )
        if source == "ALL":
            for label, source_key in source_groups:
                source_fields = tuple(
                    field for field in fields
                    if field.key in REPORT_FIELD_SOURCES and source_key in REPORT_FIELD_SOURCES[field.key]
                    and (len(REPORT_FIELD_SOURCES[field.key]) == 1 or source_key == "ROSTER_LOCK")
                )
                if source_fields:
                    groups.append((label, source_fields))
            shared = tuple(
                field for field in fields
                if field.key in REPORT_FIELD_SOURCES and len(REPORT_FIELD_SOURCES[field.key]) > 1
                and field.key not in {item.key for _, group in groups for item in group}
            )
            if shared:
                groups.append(("Shared engagement fields", shared))
        elif source in dict(REPORT_SOURCES):
            source_label = REPORT_SOURCES_BY_KEY.get(source, source)
            source_fields = tuple(field for field in fields if not field.key.startswith("employee.") and not field.key.startswith("coverage.") and not field.key.startswith("quality.") and not field.key.startswith("raw.") and field.key != "source.source_system")
            if source_fields:
                groups.append((f"{source_label} fields", source_fields))

        for source_key, source_label in SOURCE_DISPLAY_NAMES.items():
            raw_fields = tuple(field for field in fields if field.key.startswith(f"raw.{source_key}."))
            if raw_fields:
                groups.append((f"{source_label} file columns", raw_fields))

        supporting = tuple(field for field in fields if field.key.startswith("coverage.") or field.key.startswith("quality.") or field.key == "source.source_system")
        if supporting:
            groups.append(("Coverage, lineage & quality", supporting))
        return tuple(groups)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return bool(value) if isinstance(value, bool) else str(value or "").strip().lower() in {"1", "true", "yes", "y", "present"}

    @staticmethod
    def _matches(value: Any, operator: str, expected: Any, data_type: str) -> bool:
        actual = "" if value is None else str(value)
        expected_raw = expected
        expected = str(expected or "").strip()
        if operator == "is_empty":
            return not actual.strip() or (data_type == "boolean" and not ReportService._as_bool(value))
        if operator == "is_not_empty":
            return bool(actual.strip()) if data_type != "boolean" else ReportService._as_bool(value)
        if operator == "in":
            expected_values = expected_raw if isinstance(expected_raw, (list, tuple, set)) else [expected_raw]
            return any(ReportService._matches(value, "equals", item, data_type) for item in expected_values)
        if data_type == "boolean":
            return ReportService._as_bool(value) == ReportService._as_bool(expected)
        if operator == "contains":
            return expected.casefold() in actual.casefold()
        if operator == "equals":
            return actual.casefold() == expected.casefold()
        if operator == "greater_than":
            return ReportService._comparison_value(actual, data_type) > ReportService._comparison_value(expected, data_type)
        if operator == "less_than":
            return ReportService._comparison_value(actual, data_type) < ReportService._comparison_value(expected, data_type)
        if operator == "last_days":
            try:
                parsed = ReportService._parse_date(actual)
                if parsed is None:
                    return False
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - parsed).days
                return 0 <= age_days <= max(0, int(expected))
            except (TypeError, ValueError):
                return False
        return True

    @staticmethod
    def _parse_date(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        for candidate in (text, text.replace("Z", "+00:00")):
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                pass
        for pattern in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                pass
        return None

    @staticmethod
    def _comparison_value(value: Any, data_type: str) -> Any:
        text = str(value or "").strip()
        if data_type == "date":
            parsed = ReportService._parse_date(text)
            if parsed is None:
                return float("-inf")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        if data_type == "number":
            try:
                return float(text.replace(",", ""))
            except ValueError:
                return float("-inf")
        return text.casefold()

    @staticmethod
    def _field_value(field_key: str, worker: WorkerModel, engagement: WorkerEngagementModel | None, source_systems: set[str], discrepancy_count: int, raw_values: dict[str, Any] | None = None) -> Any:
        if field_key.startswith("raw."):
            return (raw_values or {}).get(field_key, "")
        if field_key == "employee.display_name":
            return worker.display_name or ""
        if field_key == "employee.email":
            return worker.canonical_email or ""
        if field_key == "employee.worker_id":
            return worker.worker_id
        if field_key == "employee.status":
            return worker.status or ""
        if field_key == "source.source_system":
            return (engagement.source_system if engagement else "") or ""
        if field_key == "coverage.roster_lock":
            return "ROSTER_LOCK" in source_systems
        if field_key == "coverage.fieldglass":
            return "RSR_SUPPLIER_WORKER_DETAILS" in source_systems
        if field_key == "coverage.accessnow":
            return "ACCESSNOW" in source_systems
        if field_key == "quality.open_discrepancies":
            return discrepancy_count
        if field_key.startswith("engagement."):
            return getattr(engagement, field_key.removeprefix("engagement."), "") if engagement else ""
        return ""

    @staticmethod
    def _preferred_engagement(engagements: list[WorkerEngagementModel]) -> WorkerEngagementModel | None:
        """Choose one engagement so report output remains one row per employee."""
        if not engagements:
            return None
        source_priority = {"ROSTER_LOCK": 3, "RSR_SUPPLIER_WORKER_DETAILS": 2, "ACCESSNOW": 1}
        engagement_fields = tuple(field.key.removeprefix("engagement.") for field in REPORT_FIELDS if field.key.startswith("engagement."))

        def score(item: WorkerEngagementModel) -> tuple[int, int, str, str]:
            completeness = sum(bool(str(getattr(item, field, "") or "").strip()) for field in engagement_fields)
            source = str(item.source_system or "").upper()
            return completeness, source_priority.get(source, 0), str(item.updated_at_utc or ""), str(item.engagement_id or "")

        return max(engagements, key=score)

    def studio_preview(
        self,
        *,
        source: str = "ALL",
        columns: list[str] | tuple[str, ...] | None = None,
        filter_field: str = "",
        filter_operator: str = "equals",
        filter_value: str = "",
        filters: list[dict[str, Any]] | None = None,
        sort_field: str = "",
        sort_direction: str = "desc",
        limit: int | str | None = None,
    ) -> ReportStudioResult:
        source = source if source in REPORT_SOURCES_BY_KEY else "ALL"
        available_fields = self.field_catalog(source)
        available_keys = {field.key for field in available_fields}
        selected_columns = tuple(key for key in (columns or ()) if key in available_keys)
        if not selected_columns:
            default_columns = ("employee.display_name", "engagement.vendor_name", "engagement.onboarding_date", "employee.status")
            selected_columns = tuple(key for key in default_columns if key in available_keys)
        fields_by_key = {field.key: field for field in available_fields}
        selected_fields = tuple(fields_by_key[key] for key in selected_columns)
        filter_field = filter_field if filter_field in available_keys else ""
        sort_field = sort_field if sort_field in available_keys and fields_by_key[sort_field].sortable else ""
        sort_direction = "asc" if sort_direction == "asc" else "desc"
        filter_specs: list[dict[str, Any]] = []
        if filters:
            for candidate in filters:
                field = str(candidate.get("field", ""))
                operator = str(candidate.get("operator", "equals"))
                value = candidate.get("value", "")
                if field not in available_keys or operator not in {"equals", "contains", "is_empty", "is_not_empty", "last_days", "greater_than", "less_than", "in"}:
                    continue
                if operator not in {"is_empty", "is_not_empty"} and not value:
                    continue
                filter_specs.append({"field": field, "operator": operator, "value": value})
        elif filter_field and (filter_value or filter_operator in {"is_empty", "is_not_empty"}):
            filter_specs = [{"field": filter_field, "operator": filter_operator, "value": filter_value}]
        parsed_limit: int | None
        if limit is None or str(limit).strip().casefold() in {"", "all", "none", "0"}:
            parsed_limit = None
        else:
            try:
                parsed_limit = max(1, int(limit))
            except (TypeError, ValueError):
                parsed_limit = None
        definition = {
            "sources": [source],
            "columns": list(selected_columns),
            "filters": filter_specs,
            "sort": ([{"field": sort_field, "direction": sort_direction}] if sort_field else []),
            "limit": parsed_limit,
        }
        if not self.database_path.exists():
            return ReportStudioResult(selected_fields, (), 0, definition, {})

        with orm_session(self.database_path) as session:
            workers = session.scalars(select(WorkerModel).where(WorkerModel.superseded_by_worker_id.is_(None))).all()
            worker_ids = {worker.worker_id for worker in workers}
            engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id.in_(worker_ids))).all() if worker_ids else []
            profiles = session.scalars(select(WorkerSourceProfileModel).where(WorkerSourceProfileModel.worker_id.in_(worker_ids))).all() if worker_ids else []
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status == "APPLIED", IngestionRecordModel.matched_worker_id.in_(worker_ids))).all() if worker_ids else []
            discrepancies = session.scalars(select(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id.in_(worker_ids), WorkerDiscrepancyModel.status == "OPEN")).all() if worker_ids else []

        engagements_by_worker: dict[str, list[WorkerEngagementModel]] = {}
        source_systems_by_worker: dict[str, set[str]] = {}
        for engagement in engagements:
            engagements_by_worker.setdefault(engagement.worker_id, []).append(engagement)
            if engagement.source_system:
                source_systems_by_worker.setdefault(engagement.worker_id, set()).add(engagement.source_system.upper())
        for profile in profiles:
            source_systems_by_worker.setdefault(profile.worker_id, set()).add((profile.source_system or "").upper())
        raw_values_by_worker_source: dict[tuple[str, str], dict[str, Any]] = {}
        raw_values_by_worker: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            profile_source = (profile.source_system or "").upper()
            try:
                payload = json.loads(profile.snapshot_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                values = {self._raw_field_key(profile_source, str(key)): value for key, value in payload.items()}
                raw_values_by_worker_source.setdefault((profile.worker_id, profile_source), {}).update(values)
                raw_values_by_worker.setdefault(profile.worker_id, {}).update(values)
        for record in records:
            record_source = (record.source_system or "").upper()
            try:
                payload = json.loads(record.payload_json or record.normalized_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and record.matched_worker_id:
                values = {self._raw_field_key(record_source, str(key)): value for key, value in payload.items()}
                raw_values_by_worker_source.setdefault((record.matched_worker_id, record_source), {}).update(values)
                raw_values_by_worker.setdefault(record.matched_worker_id, {}).update(values)
        discrepancies_by_worker: dict[str, int] = {}
        for discrepancy in discrepancies:
            if discrepancy.worker_id:
                discrepancies_by_worker[discrepancy.worker_id] = discrepancies_by_worker.get(discrepancy.worker_id, 0) + 1

        result_rows: list[dict[str, Any]] = []
        filter_options: dict[str, set[str]] = {field.key: set() for field in available_fields}
        for worker in workers:
            worker_engagements = engagements_by_worker.get(worker.worker_id, [])
            if source == "CANONICAL":
                row_engagements = [None]
            elif source == "ALL":
                row_engagements = [self._preferred_engagement(worker_engagements)] if worker_engagements else [None]
            else:
                matching_engagements = [item for item in worker_engagements if (item.source_system or "").upper() == source]
                row_engagements = [self._preferred_engagement(matching_engagements)] if matching_engagements else []
                if not row_engagements and source in source_systems_by_worker.get(worker.worker_id, set()):
                    row_engagements = [None]
            for engagement in row_engagements:
                engagement_source = (engagement.source_system if engagement else source).upper()
                raw_values = raw_values_by_worker.get(worker.worker_id, {}) if source == "ALL" else raw_values_by_worker_source.get((worker.worker_id, engagement_source), {})
                values = {field.key: self._field_value(field.key, worker, engagement, source_systems_by_worker.get(worker.worker_id, set()), discrepancies_by_worker.get(worker.worker_id, 0), raw_values) for field in selected_fields}
                for field in available_fields:
                    value = self._field_value(field.key, worker, engagement, source_systems_by_worker.get(worker.worker_id, set()), discrepancies_by_worker.get(worker.worker_id, 0), raw_values)
                    filter_options[field.key].add("" if value is None else str(value))
                if any(
                    not self._matches(
                        self._field_value(spec["field"], worker, engagement, source_systems_by_worker.get(worker.worker_id, set()), discrepancies_by_worker.get(worker.worker_id, 0), raw_values),
                        spec["operator"],
                        spec["value"],
                        fields_by_key[spec["field"]].data_type,
                    )
                    for spec in filter_specs
                ):
                    continue
                result_rows.append(values)
        total_rows = len(result_rows)
        if sort_field:
            result_rows.sort(key=lambda item: str(item.get(sort_field, "")).casefold(), reverse=sort_direction == "desc")
        normalized_filter_options = {
            field_key: tuple(sorted(values, key=lambda item: item.casefold()))
            for field_key, values in filter_options.items()
        }
        visible_rows = result_rows if parsed_limit is None else result_rows[:parsed_limit]
        return ReportStudioResult(selected_fields, tuple(visible_rows), total_rows, definition, normalized_filter_options)

    @staticmethod
    def _date_sort_key(value: str) -> tuple[int, str]:
        """Sort ISO and common workbook date strings newest first."""
        from datetime import datetime

        text = str(value or "").strip()
        for candidate in (text, text.replace("Z", "+00:00")):
            try:
                return (int(datetime.fromisoformat(candidate).timestamp()), text)
            except ValueError:
                pass
        for pattern in ("%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return (int(datetime.strptime(text, pattern).timestamp()), text)
            except ValueError:
                pass
        return (0, text)

    def new_hire_readiness(self, *, limit: int = 100) -> tuple[NewHireReadinessRow, ...]:
        """Return recent Roster Lock starters missing Fieldglass/AccessNow evidence."""
        if not self.database_path.exists():
            return ()
        limit = max(1, min(int(limit), 500))
        with orm_session(self.database_path) as session:
            workers = session.scalars(
                select(WorkerModel).where(WorkerModel.superseded_by_worker_id.is_(None))
            ).all()
            worker_ids = {worker.worker_id for worker in workers}
            workers_by_id = {worker.worker_id: worker for worker in workers}
            engagements = session.scalars(
                select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id.in_(worker_ids))
            ).all()
            profiles = session.scalars(
                select(WorkerSourceProfileModel).where(
                    WorkerSourceProfileModel.worker_id.in_(worker_ids),
                    WorkerSourceProfileModel.source_system == "ACCESSNOW",
                )
            ).all()
            roster_by_worker: dict[str, list[WorkerEngagementModel]] = {}
            fieldglass_by_worker: dict[str, list[WorkerEngagementModel]] = {}
            source_systems_by_worker: dict[str, set[str]] = {}
            for engagement in engagements:
                source_system = str(engagement.source_system or "").strip().upper()
                source_systems_by_worker.setdefault(engagement.worker_id, set()).add(source_system)
                if source_system == "ROSTER_LOCK" and str(engagement.onboarding_date or "").strip():
                    roster_by_worker.setdefault(engagement.worker_id, []).append(engagement)
                if source_system == "RSR_SUPPLIER_WORKER_DETAILS":
                    fieldglass_by_worker.setdefault(engagement.worker_id, []).append(engagement)

            accessnow_termination_by_worker: dict[str, str] = {}
            for profile in profiles:
                try:
                    payload = json.loads(profile.snapshot_json or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                termination_date = next(
                    (str(payload.get(key) or "").strip() for key in ("terminated_date", "termination_date", "deactivated_date", "end_date") if str(payload.get(key) or "").strip()),
                    "",
                )
                if termination_date:
                    current = accessnow_termination_by_worker.get(profile.worker_id, "")
                    if self._date_sort_key(termination_date) >= self._date_sort_key(current):
                        accessnow_termination_by_worker[profile.worker_id] = termination_date

            rows: list[NewHireReadinessRow] = []
            for worker_id, roster_engagements in roster_by_worker.items():
                worker = workers_by_id[worker_id]
                roster_engagement = max(roster_engagements, key=lambda item: self._date_sort_key(item.onboarding_date))
                fieldglass_engagements = fieldglass_by_worker.get(worker_id, [])
                fieldglass_engagement = max(
                    fieldglass_engagements,
                    key=lambda item: self._date_sort_key(item.onboarding_date or item.production_start_date),
                    default=None,
                )
                source_systems = source_systems_by_worker.get(worker_id, set())
                fieldglass_present = "RSR_SUPPLIER_WORKER_DETAILS" in source_systems
                accessnow_present = "ACCESSNOW" in source_systems
                if fieldglass_present and accessnow_present:
                    continue
                rows.append(NewHireReadinessRow(
                    worker_id=worker_id,
                    display_name=worker.display_name or "Unnamed worker",
                    email=worker.canonical_email or "",
                    vendor_name=roster_engagement.vendor_name or "",
                    roster_lock_role=roster_engagement.job_title or "",
                    fieldglass_job_title=fieldglass_engagement.job_title if fieldglass_engagement else "",
                    work_start_date=roster_engagement.onboarding_date,
                    status=worker.status or "",
                    accessnow_terminated_date=accessnow_termination_by_worker.get(worker_id, ""),
                    fieldglass_present=fieldglass_present,
                    accessnow_present=accessnow_present,
                ))
            rows.sort(key=lambda item: self._date_sort_key(item.work_start_date), reverse=True)
            return tuple(rows[:limit])

    @staticmethod
    def _report_date(value: str | date | None, default: date) -> date:
        if isinstance(value, date):
            return value
        parsed = parse_source_date(value) if value else None
        return parsed or default

    def termination_report(self, *, start_date: str | date | None = None, end_date: str | date | None = None) -> TerminationReport:
        """Return AccessNow terminations and attrition breakdowns for a date window."""
        today = date.today()
        end = self._report_date(end_date, today)
        start = self._report_date(start_date, end - timedelta(days=89))
        if start > end:
            start, end = end, start
        start_text, end_text = start.isoformat(), end.isoformat()
        if not self.database_path.exists():
            return TerminationReport(start_text, end_text, 0, 0, (), (), (), ())

        with orm_session(self.database_path) as session:
            workers = session.scalars(select(WorkerModel).where(WorkerModel.superseded_by_worker_id.is_(None))).all()
            worker_ids = {worker.worker_id for worker in workers}
            engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id.in_(worker_ids))).all()
            profiles = session.scalars(select(WorkerSourceProfileModel).where(
                WorkerSourceProfileModel.worker_id.in_(worker_ids),
                WorkerSourceProfileModel.source_system == "ACCESSNOW",
            )).all()

        worker_by_id = {worker.worker_id: worker for worker in workers}
        roster_by_worker: dict[str, list[WorkerEngagementModel]] = {}
        fieldglass_by_worker: dict[str, list[WorkerEngagementModel]] = {}
        for engagement in engagements:
            source = str(engagement.source_system or "").strip().upper()
            if source == "ROSTER_LOCK" and str(engagement.onboarding_date or "").strip():
                roster_by_worker.setdefault(engagement.worker_id, []).append(engagement)
            elif source == "RSR_SUPPLIER_WORKER_DETAILS":
                fieldglass_by_worker.setdefault(engagement.worker_id, []).append(engagement)

        termination_by_worker: dict[str, tuple[date, str]] = {}
        employee_id_by_worker: dict[str, str] = {}
        for profile in profiles:
            try:
                payload = json.loads(profile.snapshot_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                continue
            employee_id = str(payload.get("accessnow_employee_id") or payload.get("employee_id") or "").strip()
            if employee_id:
                employee_id_by_worker[profile.worker_id] = employee_id
            for key in ("terminated_date", "termination_date", "deactivated_date", "end_date"):
                parsed = parse_source_date(payload.get(key))
                if parsed is None:
                    continue
                raw = str(payload.get(key) or "").strip()
                current = termination_by_worker.get(profile.worker_id)
                if current is None or parsed >= current[0]:
                    termination_by_worker[profile.worker_id] = (parsed, raw)
                break

        population: list[tuple[str, str, str]] = []
        rows: list[TerminationReportRow] = []
        for worker_id, roster_engagements in roster_by_worker.items():
            worker = worker_by_id.get(worker_id)
            if worker is None:
                continue
            roster = max(roster_engagements, key=lambda item: self._date_sort_key(item.onboarding_date))
            roster_start = parse_source_date(roster.onboarding_date)
            if roster_start is None or roster_start > end:
                continue
            termination = termination_by_worker.get(worker_id)
            if termination is None or termination[0] >= start:
                population.append((worker_id, roster.vendor_name or "Unknown", roster.job_title or "Unknown role"))
            if termination is None or not (start <= termination[0] <= end):
                continue
            fieldglass = max(
                fieldglass_by_worker.get(worker_id, []),
                key=lambda item: self._date_sort_key(item.onboarding_date or item.production_start_date),
                default=None,
            )
            rows.append(TerminationReportRow(
                worker_id=worker_id,
                employee_id=employee_id_by_worker.get(worker_id, ""),
                display_name=worker.display_name or "Unnamed worker",
                email=worker.canonical_email or "",
                termination_date=termination[1],
                vendor_name=roster.vendor_name or "Unknown",
                roster_lock_role=roster.job_title or "Unknown role",
                fieldglass_job_title=fieldglass.job_title if fieldglass else "",
                work_start_date=roster.onboarding_date,
            ))

        population_by_role: dict[str, int] = {}
        population_by_vendor: dict[str, int] = {}
        for _, vendor, role in population:
            population_by_role[role] = population_by_role.get(role, 0) + 1
            population_by_vendor[vendor] = population_by_vendor.get(vendor, 0) + 1
        role_counts: dict[str, int] = {}
        vendor_counts: dict[str, int] = {}
        month_counts: dict[str, int] = {}
        for row in rows:
            role_counts[row.roster_lock_role] = role_counts.get(row.roster_lock_role, 0) + 1
            vendor_counts[row.vendor_name] = vendor_counts.get(row.vendor_name, 0) + 1
            parsed = parse_source_date(row.termination_date)
            month = parsed.strftime("%Y-%m") if parsed else "Unknown"
            month_counts[month] = month_counts.get(month, 0) + 1
        by_role = tuple(TerminationBreakdownRow(label, role_counts.get(label, 0), count) for label, count in sorted(population_by_role.items(), key=lambda item: item[0].casefold()))
        by_vendor = tuple(TerminationBreakdownRow(label, vendor_counts.get(label, 0), count) for label, count in sorted(population_by_vendor.items(), key=lambda item: item[0].casefold()))
        rows.sort(key=lambda item: self._date_sort_key(item.termination_date), reverse=True)
        return TerminationReport(start_text, end_text, len(rows), len(population), tuple(rows), by_role, by_vendor, tuple(sorted(month_counts.items(), reverse=True)))

    def snapshot(self) -> ReportSnapshot:
        as_of_utc = datetime.now(timezone.utc).isoformat()
        if not self.database_path.exists():
            return ReportSnapshot(0, 0, 0, 0, 0, 0, 0, as_of_utc, ())

        with orm_session(self.database_path) as session:
            workers = session.scalars(
                select(WorkerModel).where(WorkerModel.superseded_by_worker_id.is_(None))
            ).all()
            worker_ids = {worker.worker_id for worker in workers}
            active_ids = {worker.worker_id for worker in workers if worker.status == "ACTIVE"}

            engagements = session.scalars(
                select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id.in_(worker_ids))
            ).all()
            vendor_workers: dict[str, set[str]] = {}
            vendor_engagements: dict[str, int] = {}
            workers_with_vendor: set[str] = set()
            for engagement in engagements:
                vendor_name = str(engagement.vendor_name or "").strip()
                if not vendor_name:
                    continue
                workers_with_vendor.add(engagement.worker_id)
                vendor_workers.setdefault(vendor_name, set()).add(engagement.worker_id)
                vendor_engagements[vendor_name] = vendor_engagements.get(vendor_name, 0) + 1

            open_discrepancies = session.scalars(
                select(WorkerDiscrepancyModel).where(
                    WorkerDiscrepancyModel.status == "OPEN",
                    WorkerDiscrepancyModel.worker_id.in_(worker_ids),
                )
            ).all()
            discrepancies_by_vendor: dict[str, int] = {}
            for discrepancy in open_discrepancies:
                for vendor_name, employee_ids in vendor_workers.items():
                    if discrepancy.worker_id in employee_ids:
                        discrepancies_by_vendor[vendor_name] = discrepancies_by_vendor.get(vendor_name, 0) + 1

            vendor_rows = tuple(
                VendorReportRow(
                    vendor_name=vendor_name,
                    employee_count=len(employee_ids),
                    engagement_count=vendor_engagements[vendor_name],
                    active_count=len(employee_ids & active_ids),
                    pending_inactive_count=len(employee_ids - active_ids),
                    open_discrepancy_count=discrepancies_by_vendor.get(vendor_name, 0),
                )
                for vendor_name, employee_ids in sorted(vendor_workers.items(), key=lambda item: item[0].casefold())
            )

            return ReportSnapshot(
                total_employees=len(workers),
                active_employees=len(active_ids),
                pending_inactive_employees=len(workers) - len(active_ids),
                total_vendors=len(vendor_rows),
                employees_without_vendor=len(worker_ids - workers_with_vendor),
                open_discrepancies=len(open_discrepancies),
                total_vendor_engagements=sum(vendor_engagements.values()),
                as_of_utc=as_of_utc,
                vendors=vendor_rows,
            )
#endfile
