"""Safe draft configuration and sample preview services.

The service is intentionally independent from ImportBatch, ingestion records,
facts, rules, matching and employee promotion.  It is the first agnostic
configuration seam, not a production ingestion adapter.
"""

from __future__ import annotations

import csv
import io
import re
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from ...infrastructure.sqlite.orm import DimFieldModel, orm_session
from .configuration_contracts import (
    DRAFT_DRIFT_POLICIES,
    DRAFT_FIELD_TYPES,
    DRAFT_FORMATS,
    DRAFT_IDENTITY_ROLES,
    DRAFT_IDENTITY_STRENGTHS,
    DRAFT_TRANSFORMS,
    DraftFieldDefinition,
    DraftFieldMapping,
    MAX_IDENTITY_MATCH_FIELDS,
    DraftSourceDefinition,
)


MAX_PREVIEW_ROWS = 25
MAX_INSPECTION_ROWS = 5000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class DraftConfigurationService:
    """Validate and preview a session-backed draft without production writes."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def governed_fields(self) -> tuple[dict[str, str], ...]:
        """Read the existing governed field catalog without modifying it."""
        with orm_session(self.database_path) as session:
            fields = session.scalars(
                select(DimFieldModel)
                .where(DimFieldModel.active.is_(True))
                .order_by(DimFieldModel.label.asc(), DimFieldModel.field_key.asc())
            ).all()
            return tuple(
                {
                    "key": str(field.field_key),
                    "label": str(field.label or field.field_key),
                    "data_type": str(field.data_type or field.semantic_type or "TEXT"),
                }
                for field in fields
            )

    @staticmethod
    def inspect_structure(filename: str, content: bytes) -> dict[str, Any]:
        """Return a bounded raw grid and header candidates before schema selection."""
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Sample files are limited to 20 MB in the configuration laboratory.")
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("Choose a CSV or Excel file.")
        if suffix == ".csv":
            rows = _csv_matrix(content, ",")
            sheets = ({"name": "CSV file", "rows": tuple(rows), "header_candidates": _header_candidates(rows), "recommended_header_row": _recommend_header_row(rows), "recommended_header_rows": _recommend_header_rows(rows)},)
            return {"filename": filename, "format": "CSV", "sheet_names": (), "sheets": sheets}
        sheets = []
        for name, rows in _xlsx_matrices(content):
            sheets.append({"name": name, "rows": tuple(rows), "header_candidates": _header_candidates(rows), "recommended_header_row": _recommend_header_row(rows), "recommended_header_rows": _recommend_header_rows(rows)})
        return {"filename": filename, "format": "XLSX", "sheet_names": tuple(item["name"] for item in sheets), "sheets": tuple(sheets)}

    @staticmethod
    def validate(draft: DraftSourceDefinition) -> tuple[str, ...]:
        errors: list[str] = []
        if not draft.source_id.strip():
            errors.append("Source key is required.")
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", draft.source_id.strip()):
            errors.append("Source key may contain only letters, numbers, underscores and hyphens.")
        if not draft.display_name.strip():
            errors.append("Display name is required.")
        if draft.reader_settings.format.upper() not in DRAFT_FORMATS:
            errors.append("Choose CSV or Excel as the source format.")
        if draft.reader_settings.header_row < 1:
            errors.append("Header row must be one or greater.")
        if len(draft.reader_settings.csv_delimiter) != 1:
            errors.append("CSV delimiter must be one character.")
        if draft.schema_drift_policy not in DRAFT_DRIFT_POLICIES:
            errors.append("Choose a valid schema drift preview severity.")
        seen_source: set[str] = set()
        seen_keys: set[str] = set()
        for index, field in enumerate(draft.fields, start=1):
            source_name = field.source_name.strip()
            field_key = field.field_key.strip()
            if not source_name:
                errors.append(f"Schema field {index} needs a source field name.")
            if not field_key:
                errors.append(f"Schema field {index} needs an internal field key.")
            if source_name.casefold() in seen_source and source_name:
                errors.append(f"Schema field {index} repeats source field {source_name!r}.")
            if field_key.casefold() in seen_keys and field_key:
                errors.append(f"Schema field {index} repeats field key {field_key!r}.")
            seen_source.add(source_name.casefold())
            seen_keys.add(field_key.casefold())
            if field.data_type not in DRAFT_FIELD_TYPES:
                errors.append(f"Schema field {field_key or index} uses an unsupported type.")
            if field.identifier and field.data_type != "string":
                errors.append(f"Identifier field {field_key or index} must remain a string.")
        for mapping in draft.mappings:
            if mapping.transform_name not in DRAFT_TRANSFORMS:
                errors.append(f"Transform {mapping.transform_name!r} is not in the controlled allow-list.")
        for validation in draft.validations:
            if validation.kind not in {"required", "nullable", "identifier", "enum", "date_format", "min_length", "max_length", "regex", "duplicate_source_key"}:
                errors.append(f"Validation kind {validation.kind!r} is not supported.")
        identity = draft.identity_governance
        if identity.role not in DRAFT_IDENTITY_ROLES:
            errors.append("Choose a valid identity template role.")
        matching_fields = [item for item in identity.identifiers if item.can_match]
        if len(matching_fields) > MAX_IDENTITY_MATCH_FIELDS:
            errors.append(f"Choose no more than {MAX_IDENTITY_MATCH_FIELDS} fields for identity matching.")
        for identifier in identity.identifiers:
            if identifier.strength not in DRAFT_IDENTITY_STRENGTHS:
                errors.append(f"Identity field {identifier.field_key!r} uses an unsupported strength.")
        return tuple(errors)

    @staticmethod
    def inspect_sample(filename: str, content: bytes, *, delimiter: str = ",", sheet_name: str = "", header_row: int = 1, header_rows: Iterable[int] | None = None) -> dict[str, Any]:
        """Inspect a bounded CSV/XLSX sample and return display-only diagnostics."""
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Sample files are limited to 20 MB in the configuration laboratory.")
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("Sample inspection supports CSV and Excel files only.")
        if header_row < 1:
            raise ValueError("Header row must be one or greater.")
        selected_header_rows = _normalize_header_rows(header_rows, header_row)
        if suffix == ".csv":
            headers, rows, sheet_names = _read_csv(content, delimiter, selected_header_rows)
        else:
            headers, rows, sheet_names = _read_xlsx(content, sheet_name, selected_header_rows)
        return {
            "filename": filename,
            "format": "CSV" if suffix == ".csv" else "XLSX",
            "sheet_names": sheet_names,
            "selected_sheet": sheet_name or (sheet_names[0] if sheet_names else ""),
            "header_rows": selected_header_rows,
            "headers": tuple(headers),
            "rows_detected": len(rows),
            "rows": tuple(rows[:MAX_PREVIEW_ROWS]),
            "type_suggestions": tuple(
                {"source_name": header, "suggested_type": _infer_type(header, [row.get(header) for row in rows])}
                for header in headers
            ),
        }

    @staticmethod
    def preview(draft: DraftSourceDefinition, inspection: dict[str, Any]) -> dict[str, Any]:
        """Apply only declared draft transforms and structural checks to a sample."""
        headers = tuple(str(header) for header in inspection.get("headers", ()))
        sample_rows = tuple(inspection.get("rows", ()))
        declared_fields = tuple(field for field in draft.fields if field.source_name.strip())
        fields = tuple(field for field in declared_fields if field.include)
        mappings = {mapping.source_field.casefold(): mapping for mapping in draft.mappings if mapping.source_field.strip()}
        field_by_source = {field.source_name.casefold(): field for field in fields}
        declared_sources = {field.source_name.casefold() for field in declared_fields}
        unknown_fields = tuple(header for header in headers if header.casefold() not in declared_sources)
        excluded_fields = tuple(field.source_name for field in declared_fields if not field.include)
        missing_fields = tuple(field.source_name for field in fields if field.source_name.casefold() not in {header.casefold() for header in headers})
        normalized_rows: list[dict[str, Any]] = []
        invalid_rows: list[dict[str, Any]] = []
        for row_number, source_row in enumerate(sample_rows, start=1):
            normalized: dict[str, Any] = {}
            errors: list[str] = []
            for field in fields:
                raw_value = source_row.get(field.source_name, "")
                value = _stringify_value(raw_value)
                mapping = mappings.get(field.source_name.casefold())
                value = _apply_transform(value, mapping.transform_name if mapping else field.transform_name)
                target_key = mapping.target_field.strip() if mapping and mapping.target_field.strip() else field.field_key.strip()
                normalized[target_key] = value
                errors.extend(_validate_value(field, value))
            errors.extend(_validate_declared_constraints(draft, normalized, fields))
            display_row = {key: value for key, value in normalized.items()}
            if errors:
                invalid_rows.append({"row_number": row_number, "errors": tuple(errors), "values": display_row})
            normalized_rows.append(display_row)
        required_missing = tuple(field.source_name for field in fields if field.required and field.source_name.casefold() not in {header.casefold() for header in headers})
        diagnostics = []
        diagnostics.extend({"severity": draft.schema_drift_policy, "message": f"Unknown field: {field}"} for field in unknown_fields)
        diagnostics.extend({"severity": "BLOCKING", "message": f"Missing required field: {field}"} for field in required_missing)
        diagnostics.extend({"severity": "WARNING", "message": f"Missing optional field: {field}"} for field in missing_fields if field not in required_missing)
        diagnostics.extend({"severity": "WARNING", "message": f"Row {item['row_number']}: {error}"} for item in invalid_rows for error in item["errors"])
        included_fields = tuple(field.source_name for field in fields if field.source_name.casefold() in {header.casefold() for header in headers})
        return {
            "sample": inspection,
            "rows_detected": inspection.get("rows_detected", 0),
            "fields_detected": len(headers),
            "included_fields": included_fields,
            "excluded_fields": excluded_fields,
            # Kept as a compatibility alias for older preview consumers. The
            # configuration laboratory no longer maps to canonical fields.
            "mapped_fields": (),
            "unmapped_fields": unknown_fields,
            "missing_required_fields": required_missing,
            "missing_optional_fields": tuple(field for field in missing_fields if field not in required_missing),
            "invalid_rows": tuple(invalid_rows),
            "diagnostics": tuple(diagnostics),
            "normalized_rows": tuple(normalized_rows[:MAX_PREVIEW_ROWS]),
        }


def _read_csv(content: bytes, delimiter: str, header_rows: tuple[int, ...]) -> tuple[tuple[str, ...], list[dict[str, Any]], tuple[str, ...]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter or ",")
    rows = list(reader)
    if len(rows) < max(header_rows):
        return (), [], ()
    headers = _compose_headers(rows, header_rows)
    data = [dict(zip(headers, (_stringify_value(value) for value in row))) for row in rows[max(header_rows):] if any(str(value).strip() for value in row)]
    return tuple(headers), data[:MAX_INSPECTION_ROWS], ()


def _csv_matrix(content: bytes, delimiter: str) -> list[tuple[str, ...]]:
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig", errors="replace")), delimiter=delimiter or ",")
    return [tuple(_stringify_value(value) for value in row) for row in list(reader)[:12]]


def _read_xlsx(content: bytes, sheet_name: str, header_rows: tuple[int, ...]) -> tuple[tuple[str, ...], list[dict[str, Any]], tuple[str, ...]]:
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("Excel sample inspection requires openpyxl.") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        names = tuple(str(name) for name in workbook.sheetnames)
        if not names:
            return (), [], ()
        selected = sheet_name if sheet_name in names else names[0]
        values = list(workbook[selected].iter_rows(values_only=True))
        if len(values) < max(header_rows):
            return (), [], names
        headers = _compose_headers(values, header_rows)
        data = [dict(zip(headers, (_stringify_value(value) for value in row))) for row in values[max(header_rows):] if any(value not in (None, "") for value in row)]
        return tuple(headers), data[:MAX_INSPECTION_ROWS], names
    finally:
        workbook.close()


def _xlsx_matrices(content: bytes) -> tuple[tuple[str, list[tuple[str, ...]]], ...]:
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("Excel sample inspection requires openpyxl.") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        return tuple(
            (
                str(name),
                [
                    tuple(_stringify_value(value) for value in row)
                    for row in list(workbook[name].iter_rows(values_only=True))[:12]
                ],
            )
            for name in workbook.sheetnames
        )
    finally:
        workbook.close()


def _header_candidates(rows: list[tuple[str, ...]]) -> tuple[dict[str, Any], ...]:
    candidates = []
    for index, row in enumerate(rows, start=1):
        values = tuple(str(value).strip() for value in row)
        if any(values):
            candidates.append({"row_number": index, "values": values})
    return tuple(candidates)


def _recommend_header_row(rows: list[tuple[str, ...]]) -> int:
    """Suggest the first row that looks like field names, not report data."""
    candidates: list[tuple[int, int, int]] = []
    for index, row in enumerate(rows, start=1):
        values = [str(value).strip() for value in row if str(value).strip()]
        if len(values) < 2:
            continue
        text_like = sum(1 for value in values if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value))
        if text_like / len(values) >= 0.7:
            candidates.append((text_like, len(values), index))
    if not candidates:
        return 1
    return max(candidates, key=lambda item: (item[0], item[1], -item[2]))[2]


def _recommend_header_rows(rows: list[tuple[str, ...]]) -> tuple[int, ...]:
    """Include populated context rows when the primary row has duplicate labels."""
    primary = _recommend_header_row(rows)
    if primary <= 1 or primary > len(rows):
        return (primary,)
    primary_values = [str(value).strip() for value in rows[primary - 1]]
    counts: dict[str, int] = {}
    for value in primary_values:
        if value:
            counts[value.casefold()] = counts.get(value.casefold(), 0) + 1
    duplicate_columns = {index for index, value in enumerate(primary_values) if value and counts.get(value.casefold(), 0) > 1}
    if not duplicate_columns:
        return (primary,)
    contextual_rows = [
        row_number
        for row_number in range(1, primary)
        if any(index < len(rows[row_number - 1]) and str(rows[row_number - 1][index]).strip() for index in duplicate_columns)
    ]
    return tuple(contextual_rows + [primary])


def _normalize_header_rows(header_rows: Iterable[int] | None, header_row: int) -> tuple[int, ...]:
    values = tuple(sorted({int(value) for value in (header_rows or (header_row,)) if int(value) > 0}))
    return values or (header_row,)


def _compose_headers(rows: list[Iterable[Any]], header_rows: tuple[int, ...]) -> list[str]:
    width = max((len(row) for row in rows), default=0)
    composed: list[str] = []
    for column_index in range(width):
        parts = []
        for row_number in header_rows:
            row = rows[row_number - 1]
            value = _stringify_value(row[column_index]).strip() if column_index < len(row) else ""
            if value and value not in parts:
                parts.append(value)
        composed.append(" · ".join(parts) or f"Source Column {column_index + 1}")
    return _unique_headers(composed)


def _unique_headers(row: Iterable[Any]) -> list[str]:
    counts: dict[str, int] = {}
    headers: list[str] = []
    for index, value in enumerate(row, start=1):
        base = str(value or "").strip() or f"Source Column {index}"
        counts[base] = counts.get(base, 0) + 1
        headers.append(base if counts[base] == 1 else f"{base} [{counts[base]}]")
    return headers


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _infer_type(field_name: str, values: Iterable[Any]) -> str:
    text_values = [_stringify_value(value).strip() for value in values if _stringify_value(value).strip()]
    lowered = field_name.casefold()
    if any(token in lowered for token in ("id", "key", "number", "nuid")) or any(value.startswith("0") and value.isdigit() for value in text_values):
        return "string"
    if text_values and all(value.casefold() in {"true", "false", "yes", "no"} for value in text_values):
        return "boolean"
    if text_values and all(re.fullmatch(r"[-+]?\d+", value) for value in text_values):
        return "integer"
    if text_values and all(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value) for value in text_values):
        return "decimal"
    if text_values and all(_looks_like_date(value) for value in text_values):
        return "date"
    return "string"


def suggest_source_transform(field_name: str) -> str:
    """Suggest a safe source-level cleanup from explainable column-name signals."""
    lowered = str(field_name or "").casefold()
    if any(token in lowered for token in ("email", "e-mail", "mail address")):
        return "normalize_email"
    if any(token in lowered for token in ("date", "datetime", "timestamp", "time")):
        return "parse_date"
    if any(token in lowered for token in ("id", "key", "number", "nuid", "npn")):
        return "normalize_id"
    return "identity"


def _looks_like_date(value: str) -> bool:
    for parser in (date.fromisoformat, lambda item: datetime.strptime(item, "%m/%d/%Y").date()):
        try:
            parser(value[:10])
            return True
        except (TypeError, ValueError):
            continue
    return False


def _apply_transform(value: str, transform_name: str) -> str:
    if transform_name == "trim":
        return value.strip()
    if transform_name == "lower":
        return value.lower()
    if transform_name == "upper":
        return value.upper()
    if transform_name == "normalize_email":
        return value.strip().lower()
    if transform_name == "normalize_id":
        return value.strip()
    if transform_name == "parse_date":
        return value.strip()
    return value


def _validate_value(field: DraftFieldDefinition, value: str) -> list[str]:
    if not value:
        if field.required:
            return [f"{field.source_name} is required"]
        if field.nullable:
            return []
        return [f"{field.source_name} may not be empty"]
    if field.identifier and not isinstance(value, str):
        return [f"{field.source_name} identifiers remain strings"]
    if field.data_type == "integer" and not re.fullmatch(r"[-+]?\d+", value):
        return [f"{field.source_name} is not an integer"]
    if field.data_type == "decimal":
        try:
            float(value)
        except ValueError:
            return [f"{field.source_name} is not a decimal"]
    if field.data_type == "boolean" and value.casefold() not in {"true", "false", "yes", "no"}:
        return [f"{field.source_name} is not boolean"]
    if field.data_type in {"date", "datetime"} and not _looks_like_date(value):
        return [f"{field.source_name} has an invalid date value"]
    if field.data_type == "enum" and field.enum_values and value not in field.enum_values:
        return [f"{field.source_name} is outside the configured enum values"]
    return []


def _validate_declared_constraints(
    draft: DraftSourceDefinition,
    normalized: dict[str, Any],
    fields: tuple[DraftFieldDefinition, ...],
) -> list[str]:
    """Apply the small structural subset represented by the draft UI."""
    fields_by_key = {field.field_key: field for field in fields}
    errors: list[str] = []
    for validation in draft.validations:
        field = fields_by_key.get(validation.field_key)
        if field is None:
            continue
        value = str(normalized.get(field.field_key, ""))
        if validation.kind == "required" and not value:
            errors.append(f"{field.source_name} is required")
        elif validation.kind == "nullable" and validation.parameter.casefold() in {"false", "no", "0"} and not value:
            errors.append(f"{field.source_name} may not be null")
        elif validation.kind == "identifier" and value and not isinstance(value, str):
            errors.append(f"{field.source_name} identifier must remain a string")
        elif validation.kind == "enum" and validation.parameter and value not in {item.strip() for item in re.split(r"[,|]", validation.parameter) if item.strip()}:
            errors.append(f"{field.source_name} is outside the configured enum values")
        elif validation.kind == "date_format" and value and not _looks_like_date(value):
            errors.append(f"{field.source_name} has an invalid date value")
        elif validation.kind == "min_length" and value and len(value) < _safe_int(validation.parameter, 0):
            errors.append(f"{field.source_name} is shorter than the configured minimum")
        elif validation.kind == "max_length" and value and len(value) > _safe_int(validation.parameter, 10**9):
            errors.append(f"{field.source_name} is longer than the configured maximum")
        elif validation.kind == "regex" and value and validation.parameter:
            try:
                matches = re.fullmatch(validation.parameter, value)
            except re.error:
                matches = None
            if not matches:
                errors.append(f"{field.source_name} does not match the configured pattern")
    return errors


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
