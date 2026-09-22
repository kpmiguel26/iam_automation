"""Administrative routes for the isolated ingestion configuration laboratory."""

from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any, Callable
import re
import time
import uuid
from dataclasses import replace

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.ingestion.configuration_contracts import (
    DRAFT_DRIFT_POLICIES,
    DRAFT_FIELD_TYPES,
    DRAFT_FORMATS,
    DRAFT_IDENTITY_ROLE_DESCRIPTIONS,
    DRAFT_IDENTITY_ROLE_LABELS,
    DRAFT_IDENTITY_ROLES,
    DRAFT_IDENTITY_STRENGTHS,
    DRAFT_TRANSFORM_DESCRIPTIONS,
    DRAFT_TRANSFORM_LABELS,
    DRAFT_TRANSFORMS,
    DRAFT_VALIDATION_KINDS,
    DraftFieldDefinition,
    DraftFieldMapping,
    DraftIdentityGovernance,
    DraftIdentityIdentifier,
    DraftReaderSettings,
    DraftRecognitionSettings,
    DraftSourceDefinition,
    DraftValidationDefinition,
)
from ...application.ingestion.configuration_service import DraftConfigurationService, suggest_source_transform
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role


SESSION_KEY = "ingestion_configuration_draft"


def create_ingestion_configuration_blueprint(database_path: Path) -> Blueprint:
    """Create the non-persistent draft configuration blueprint."""
    blueprint = Blueprint("ingestion_configuration", __name__, url_prefix="/admin/ingestion-sources")
    service = DraftConfigurationService(database_path)
    sample_artifacts: dict[str, tuple[float, str, bytes]] = {}

    def admin_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)

        return wrapped

    def render_page(*, draft: DraftSourceDefinition, message: str | None = None, error: str | None = None, preview: dict | None = None, structure: dict | None = None, inspection: dict | None = None, artifact_id: str | None = None, raw_rows: tuple | None = None, recommended_header_rows: tuple[int, ...] = (), raw_column_count: int | None = None, status_code: int = 200):
        return render_template(
            "admin/ingestion_source_configuration.html",
            draft=draft,
            formats=DRAFT_FORMATS,
            field_types=DRAFT_FIELD_TYPES,
            transforms=DRAFT_TRANSFORMS,
            transform_labels=DRAFT_TRANSFORM_LABELS,
            transform_descriptions=DRAFT_TRANSFORM_DESCRIPTIONS,
            identity_roles=DRAFT_IDENTITY_ROLES,
            identity_role_labels=DRAFT_IDENTITY_ROLE_LABELS,
            identity_role_descriptions=DRAFT_IDENTITY_ROLE_DESCRIPTIONS,
            identity_strengths=DRAFT_IDENTITY_STRENGTHS,
            identity_identifier_by_field={item.field_key: item for item in draft.identity_governance.identifiers},
            identity_recommendations={field.field_key: _identity_recommendation(field) for field in draft.fields},
            validation_kinds=DRAFT_VALIDATION_KINDS,
            drift_policies=DRAFT_DRIFT_POLICIES,
            structure=structure,
            inspection=inspection,
            artifact_id=artifact_id,
            raw_rows=raw_rows or (structure["sheets"][0].get("rows", ()) if structure and structure.get("sheets") else ()),
            raw_column_count=raw_column_count or _raw_column_count(raw_rows or (structure["sheets"][0].get("rows", ()) if structure and structure.get("sheets") else ())),
            recommended_header_rows=recommended_header_rows or (structure["sheets"][0].get("recommended_header_rows", ()) if structure and structure.get("sheets") else ()),
            candidates=(structure["sheets"][0]["header_candidates"] if structure and structure.get("sheets") else ()),
            message=message,
            error=error,
            preview=preview,
        ), status_code

    def store_sample(filename: str, content: bytes) -> str:
        now = time.monotonic()
        for key, (created, _name, _content) in tuple(sample_artifacts.items()):
            if now - created > 1800:
                sample_artifacts.pop(key, None)
        artifact_id = uuid.uuid4().hex
        sample_artifacts[artifact_id] = (now, filename, content)
        return artifact_id

    def get_sample(artifact_id: str) -> tuple[str, bytes] | None:
        item = sample_artifacts.get(str(artifact_id or ""))
        if item is None or time.monotonic() - item[0] > 1800:
            sample_artifacts.pop(str(artifact_id or ""), None)
            return None
        return item[1], item[2]

    def partial_or_page(template: str, *, draft: DraftSourceDefinition, status_code: int = 200, **context: Any):
        if request.headers.get("HX-Request") == "true":
            return render_template(
                template,
                draft=draft,
                formats=DRAFT_FORMATS,
                field_types=DRAFT_FIELD_TYPES,
                transforms=DRAFT_TRANSFORMS,
                transform_labels=DRAFT_TRANSFORM_LABELS,
                transform_descriptions=DRAFT_TRANSFORM_DESCRIPTIONS,
                identity_roles=DRAFT_IDENTITY_ROLES,
                identity_role_labels=DRAFT_IDENTITY_ROLE_LABELS,
                identity_role_descriptions=DRAFT_IDENTITY_ROLE_DESCRIPTIONS,
                identity_strengths=DRAFT_IDENTITY_STRENGTHS,
                identity_identifier_by_field={item.field_key: item for item in draft.identity_governance.identifiers},
                identity_recommendations={field.field_key: _identity_recommendation(field) for field in draft.fields},
                validation_kinds=DRAFT_VALIDATION_KINDS,
                drift_policies=DRAFT_DRIFT_POLICIES,
                raw_column_count=_raw_column_count(context.get("raw_rows", ())),
                **context,
            ), status_code
        return render_page(draft=draft, status_code=status_code, **context)

    @blueprint.post("/sample/inspect")
    @admin_required
    def inspect_sample_structure():
        upload = request.files.get("sample_file")
        if not upload or not upload.filename:
            return partial_or_page("admin/_ingestion_sample_structure.html", draft=DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), error="Choose a CSV or Excel file first.", status_code=400)
        try:
            content = upload.read()
            artifact_id = store_sample(upload.filename, content)
            structure = service.inspect_structure(upload.filename, content)
            draft = _draft_with_source_basics(DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), request.form, upload.filename)
            session[SESSION_KEY] = draft.to_dict()
            candidates = structure["sheets"][0]["header_candidates"] if structure.get("sheets") else ()
            sheet = structure["sheets"][0] if structure.get("sheets") else {}
            return partial_or_page("admin/_ingestion_sample_structure.html", draft=draft, structure=structure, artifact_id=artifact_id, candidates=candidates, raw_rows=tuple(sheet.get("rows", ())), recommended_header_rows=tuple(sheet.get("recommended_header_rows", ())), message="File read successfully. Choose the header rows to continue.")
        except (ValueError, RuntimeError) as exc:
            return partial_or_page("admin/_ingestion_sample_structure.html", draft=DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), error=str(exc), status_code=400)

    @blueprint.get("/sample/headers")
    @admin_required
    def sample_headers():
        artifact = get_sample(request.args.get("artifact_id", ""))
        if artifact is None:
            return "The sample preview expired. Read the file again.", 410
        filename, content = artifact
        structure = service.inspect_structure(filename, content)
        selected_sheet = request.args.get("sheet_name", "")
        candidate = next((item for item in structure["sheets"] if item["name"] == selected_sheet), structure["sheets"][0] if structure["sheets"] else {"header_candidates": ()})
        candidates = candidate["header_candidates"]
        if request.headers.get("HX-Request") == "true":
            raw_rows = tuple(candidate.get("rows", ()))
            return render_template("admin/_ingestion_header_choices.html", artifact_id=request.args.get("artifact_id", ""), structure=structure, selected_sheet=selected_sheet, candidates=candidates, raw_rows=raw_rows, raw_column_count=_raw_column_count(raw_rows), recommended_header_rows=tuple(candidate.get("recommended_header_rows", ())))
        return render_page(
            draft=DraftSourceDefinition.from_dict(session.get(SESSION_KEY)),
            structure=structure,
            artifact_id=request.args.get("artifact_id", ""),
            candidates=candidates,
            raw_rows=tuple(candidate.get("rows", ())),
            raw_column_count=_raw_column_count(tuple(candidate.get("rows", ()))),
            recommended_header_rows=tuple(candidate.get("recommended_header_rows", ())),
        )

    @blueprint.post("/sample/select")
    @admin_required
    def select_sample_header():
        artifact_id = request.form.get("artifact_id", "")
        artifact = get_sample(artifact_id)
        if artifact is None:
            return partial_or_page("admin/_ingestion_sample_structure.html", draft=DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), error="The sample preview expired. Read the file again.", status_code=410)
        filename, content = artifact
        try:
            selected_rows = tuple(sorted({int(value) for value in request.form.getlist("header_rows") if int(value) > 0}))
            header_row = int(request.form.get("header_row", str(max(selected_rows) if selected_rows else "1")))
            header_rows = selected_rows or (header_row,)
            sheet_name = request.form.get("sheet_name", "")
            inspection = service.inspect_sample(filename, content, delimiter=request.form.get("csv_delimiter", ","), sheet_name=sheet_name, header_row=header_row, header_rows=header_rows)
            draft = _draft_from_inspection(DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), inspection, filename)
            session[SESSION_KEY] = draft.to_dict()
            session["ingestion_sample_selection"] = {"artifact_id": artifact_id, "sheet_name": sheet_name, "header_row": header_row, "header_rows": header_rows}
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, artifact_id=artifact_id, message="Header selected. Review the sample rows, then choose the source columns to import.")
        except (ValueError, RuntimeError) as exc:
            return partial_or_page("admin/_ingestion_sample_structure.html", draft=DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), error=str(exc), status_code=400)

    @blueprint.post("/draft/mapping")
    @admin_required
    def save_draft_mapping():
        draft = _draft_from_mapping_form(DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), request.form)
        session[SESSION_KEY] = draft.to_dict()
        selection = session.get("ingestion_sample_selection") or {}
        artifact = get_sample(str(selection.get("artifact_id", "")))
        if artifact is None:
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, error="The sample preview expired. Read the file again.", status_code=410)
        header_rows = _selected_header_rows(selection)
        inspection = service.inspect_sample(artifact[0], artifact[1], sheet_name=str(selection.get("sheet_name", "")), header_row=max(header_rows), header_rows=header_rows)
        return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, artifact_id=str(selection.get("artifact_id", "")), message="Source schema saved in this browser session. It is still a draft.")

    @blueprint.post("/sample/preview")
    @admin_required
    def preview_sample():
        draft = DraftSourceDefinition.from_dict(session.get(SESSION_KEY))
        selection = session.get("ingestion_sample_selection") or {}
        artifact = get_sample(str(selection.get("artifact_id", "")))
        if artifact is None:
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, error="The sample preview expired. Read the file again.", status_code=410)
        header_rows = _selected_header_rows(selection)
        inspection = service.inspect_sample(artifact[0], artifact[1], sheet_name=str(selection.get("sheet_name", "")), header_row=max(header_rows), header_rows=header_rows)
        return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, preview=service.preview(draft, inspection), artifact_id=str(selection.get("artifact_id", "")), message="Preview completed in memory. No production ingestion objects were created.")

    @blueprint.route("", methods=["GET", "POST"])
    @admin_required
    def configuration_page():
        draft = DraftSourceDefinition.from_dict(session.get(SESSION_KEY))
        if request.method == "GET":
            return render_page(draft=draft)

        action = request.form.get("action", "save").strip().lower()
        if request.form.get("remove_field_index") is not None:
            action = "remove_field"
        if action == "reset":
            session.pop(SESSION_KEY, None)
            return redirect(url_for("ingestion_configuration.configuration_page"))

        draft = _draft_from_form(request.form)
        errors = DraftConfigurationService.validate(draft)
        if action == "add_field":
            draft = _with_field(draft, DraftFieldDefinition(source_name="", field_key=""))
            session[SESSION_KEY] = draft.to_dict()
            return redirect(url_for("ingestion_configuration.configuration_page"))
        if action == "remove_field":
            try:
                index = int(request.form.get("remove_field_index", "-1"))
            except ValueError:
                index = -1
            draft = _without_field(draft, index)
            session[SESSION_KEY] = draft.to_dict()
            return redirect(url_for("ingestion_configuration.configuration_page"))

        if errors and action in {"save", "preview"}:
            return render_page(draft=draft, error=" ".join(errors), status_code=400)
        if action == "save":
            session[SESSION_KEY] = draft.to_dict()
            return render_page(draft=draft, message="Draft saved in this browser session. It is not active and is not persisted to the production database.")
        if action == "preview":
            upload = request.files.get("sample_file")
            if not upload or not upload.filename:
                return render_page(draft=draft, error="Choose a CSV or Excel sample file for the isolated preview.", status_code=400)
            try:
                content = upload.read()
                inspection = service.inspect_sample(
                    upload.filename,
                    content,
                    delimiter=draft.reader_settings.csv_delimiter,
                    sheet_name=draft.reader_settings.sheet_name,
                    header_row=draft.reader_settings.header_row,
                )
                preview = service.preview(draft, inspection)
                return render_page(draft=draft, inspection=inspection, preview=preview, message="Preview completed in memory. No production ingestion objects were created.")
            except (ValueError, RuntimeError) as exc:
                return render_page(draft=draft, error=str(exc), status_code=400)
        return render_page(draft=draft, error="Choose a supported draft action.", status_code=400)

    return blueprint


def _draft_from_form(form) -> DraftSourceDefinition:
    source_id = form.get("source_id", "").strip()
    display_name = form.get("display_name", "").strip()
    description = form.get("description", "").strip()
    source_format = form.get("format", "XLSX").strip().upper() or "XLSX"
    watched_path = form.get("watched_path", "").strip()
    filename_pattern = form.get("filename_pattern", "").strip()
    sheet_name = form.get("sheet_name", "").strip()
    header_row = _positive_int(form.get("header_row", "1"), default=1)
    delimiter = form.get("csv_delimiter", ",") or ","
    required_headers = tuple(item.strip() for item in form.get("required_headers", "").split(",") if item.strip())
    source_extension = ".csv" if source_format == "CSV" else ".xlsx"

    source_names = form.getlist("field_source_name")
    fields: list[DraftFieldDefinition] = []
    mappings: list[DraftFieldMapping] = []
    for index, source_name in enumerate(source_names):
        field_key = _indexed(form, "field_key", index)
        data_type = _indexed(form, "field_type", index) or "string"
        enum_values = tuple(item.strip() for item in _indexed(form, "field_enum_values", index).split(",") if item.strip())
        fields.append(
            DraftFieldDefinition(
                source_name=source_name.strip(),
                field_key=field_key.strip(),
                data_type=data_type,
                required=form.get(f"field_required_{index}") == "on",
                nullable=form.get(f"field_nullable_{index}") == "on",
                identifier=form.get(f"field_identifier_{index}") == "on",
                enum_values=enum_values,
            )
        )
        target = _indexed(form, "mapping_target", index).strip()
        if target:
            mappings.append(DraftFieldMapping(source_field=source_name.strip(), target_field=target, transform_name=_indexed(form, "mapping_transform", index) or "identity"))

    validations = tuple(
        DraftValidationDefinition(
            kind=kind.strip(),
            field_key=_indexed(form, "validation_field", index).strip(),
            parameter=_indexed(form, "validation_parameter", index).strip(),
        )
        for index, kind in enumerate(form.getlist("validation_kind"))
        if kind.strip()
    )
    return DraftSourceDefinition(
        source_id=source_id,
        display_name=display_name,
        description=description,
        reader_settings=DraftReaderSettings(
            format=source_format,
            watched_path=watched_path,
            filename_pattern=filename_pattern,
            sheet_name=sheet_name,
            header_row=header_row,
            header_rows=(header_row,),
            csv_delimiter=delimiter[0],
        ),
        recognition_settings=DraftRecognitionSettings(
            filename_pattern=filename_pattern,
            extension=source_extension,
            sheet_name=sheet_name,
            required_headers=required_headers,
        ),
        fields=tuple(fields),
        mappings=tuple(mappings),
        validations=validations,
        schema_drift_policy=form.get("schema_drift_policy", "WARNING").strip().upper() or "WARNING",
    )


def _draft_with_source_basics(draft: DraftSourceDefinition, form, filename: str) -> DraftSourceDefinition:
    stem = Path(filename).stem
    source_id = str(form.get("source_id", "")).strip() or draft.source_id or _slug(stem).upper()
    display_name = str(form.get("display_name", "")).strip() or draft.display_name or stem.replace("_", " ").replace("-", " ").title()
    description = str(form.get("description", "")).strip() or draft.description
    return replace(draft, source_id=source_id, display_name=display_name, description=description)


def _draft_from_inspection(draft: DraftSourceDefinition, inspection: dict[str, Any], filename: str) -> DraftSourceDefinition:
    existing = {field.source_name.casefold(): field for field in draft.fields}
    suggestions = {item["source_name"]: item["suggested_type"] for item in inspection.get("type_suggestions", ())}
    fields = []
    for header in inspection.get("headers", ()):
        inferred_type = str(suggestions.get(header, "string"))
        inferred_transform = suggest_source_transform(header)
        previous = existing.get(header.casefold())
        if previous is None:
            fields.append(DraftFieldDefinition(
                source_name=header,
                field_key=_suggest_field_key(header),
                data_type=inferred_type,
                inferred_type=inferred_type,
                transform_name=inferred_transform,
                inferred_transform=inferred_transform,
            ))
        else:
            fields.append(replace(previous, source_name=header, inferred_type=inferred_type, inferred_transform=inferred_transform))
    fields = tuple(fields)
    return replace(
        _draft_with_source_basics(draft, {}, filename),
        fields=fields,
        reader_settings=replace(draft.reader_settings, format=str(inspection.get("format", "XLSX")), sheet_name=str(inspection.get("selected_sheet", "")), header_row=max(tuple(inspection.get("header_rows", (1,)))), header_rows=tuple(inspection.get("header_rows", (1,)))),
        recognition_settings=replace(draft.recognition_settings, extension=".csv" if inspection.get("format") == "CSV" else ".xlsx", sheet_name=str(inspection.get("selected_sheet", "")), required_headers=tuple(str(header) for header in inspection.get("headers", ()))),
        # The configuration laboratory describes source schema only. Canonical
        # or employee mappings are intentionally deferred to the Employee Engine.
        mappings=(),
    )


def _draft_from_mapping_form(draft: DraftSourceDefinition, form) -> DraftSourceDefinition:
    fields = tuple(
        replace(
            field,
            include=form.get(f"field_include_{index}") == "on",
            field_key=str(form.get(f"field_key_{index}", field.field_key)).strip() or field.field_key,
            data_type=str(form.get(f"field_type_{index}", field.data_type)).strip() or field.data_type,
            transform_name=str(form.get(f"field_transform_{index}", field.transform_name)).strip() or field.transform_name,
        )
        for index, field in enumerate(draft.fields)
    )
    return replace(
        _draft_with_source_basics(draft, form, draft.reader_settings.filename_pattern or draft.display_name),
        fields=fields,
        identity_governance=_identity_governance_from_form(draft, fields, form),
        mappings=(),
    )


def _identity_governance_from_form(
    draft: DraftSourceDefinition,
    fields: tuple[DraftFieldDefinition, ...],
    form,
) -> DraftIdentityGovernance:
    """Read identity authority as draft metadata; never execute it here."""
    role = str(form.get("identity_role", draft.identity_governance.role)).strip().upper()
    if role not in DRAFT_IDENTITY_ROLES:
        role = "EVIDENCE_ONLY"
    can_create_employee = form.get("identity_can_create_employee") == "on"
    identifiers: list[DraftIdentityIdentifier] = []
    for index, source_field in enumerate(fields):
        if not source_field.include:
            continue
        field_key = source_field.field_key.strip()
        if not field_key:
            continue
        can_match = form.get(f"identity_field_{index}_match") == "on"
        can_create_identity = form.get(f"identity_field_{index}_create") == "on"
        strength = str(form.get(f"identity_field_{index}_strength", "SUPPORTING")).strip().upper()
        if strength not in DRAFT_IDENTITY_STRENGTHS:
            strength = "SUPPORTING"
        if role != "IDENTITY_SEED":
            can_create_identity = False
        if strength != "STRONG":
            can_create_identity = False
        if role == "EVIDENCE_ONLY":
            can_match = False
        if can_match or can_create_identity:
            identifiers.append(
                DraftIdentityIdentifier(
                    field_key=field_key,
                    strength=strength,
                    can_match=can_match,
                    can_create_identity=can_create_identity,
                )
            )
    if role != "IDENTITY_SEED":
        can_create_employee = False
    return DraftIdentityGovernance(
        role=role,
        can_create_employee=can_create_employee,
        identifiers=tuple(identifiers),
    )


def _selected_header_rows(selection: dict[str, Any]) -> tuple[int, ...]:
    values = tuple(sorted({int(value) for value in selection.get("header_rows", ()) if int(value) > 0}))
    return values or (int(selection.get("header_row", 1) or 1),)


def _raw_column_count(rows: tuple | list) -> int:
    return max((len(row) for row in rows), default=0)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "source_field"


def _suggest_field_key(header: str) -> str:
    """Keep meaningful qualifiers when a multiline header ends in a duplicate label."""
    lowered = str(header or "").casefold()
    if "nuid" in lowered and "logonid" in lowered:
        return "nuid"
    if "npn" in lowered and "logonid" in lowered:
        return "npn"
    if "user principal name" in lowered:
        return "user_principal_name"
    return _slug(header)


def _identity_recommendation(field: DraftFieldDefinition) -> str:
    """Return an explainable hint; the UI never turns it into authority."""
    key = f"{field.field_key} {field.source_name}".casefold()
    if any(token in key for token in ("employee_id", "employee_number", "employee number", "nuid")):
        return "Strong candidate: review for matching and, if governed, identity creation."
    if any(token in key for token in ("npn", "logonid", "logon id", "user_principal_name", "user principal name", "email")):
        return "Useful matching signal: do not use it alone to create an identity."
    if any(token in key for token in ("name", "hire_date", "hire date", "start_date", "start date")):
        return "Supporting context only: it should not create an identity by itself."
    return "No authority suggested. Select it only if the source is governed for this use."


def _positive_int(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _indexed(form, prefix: str, index: int) -> str:
    return str(form.get(f"{prefix}_{index}", ""))


def _with_field(draft: DraftSourceDefinition, field: DraftFieldDefinition) -> DraftSourceDefinition:
    return DraftSourceDefinition(
        source_id=draft.source_id,
        display_name=draft.display_name,
        description=draft.description,
        reader_settings=draft.reader_settings,
        recognition_settings=draft.recognition_settings,
        fields=draft.fields + (field,),
        identity_governance=draft.identity_governance,
        mappings=draft.mappings,
        validations=draft.validations,
        schema_drift_policy=draft.schema_drift_policy,
    )


def _without_field(draft: DraftSourceDefinition, index: int) -> DraftSourceDefinition:
    fields = tuple(field for position, field in enumerate(draft.fields) if position != index)
    removed_source = draft.fields[index].source_name if 0 <= index < len(draft.fields) else None
    removed_field_key = draft.fields[index].field_key if 0 <= index < len(draft.fields) else None
    return DraftSourceDefinition(
        source_id=draft.source_id,
        display_name=draft.display_name,
        description=draft.description,
        reader_settings=draft.reader_settings,
        recognition_settings=draft.recognition_settings,
        fields=fields,
        identity_governance=DraftIdentityGovernance(
            role=draft.identity_governance.role,
            can_create_employee=draft.identity_governance.can_create_employee,
            identifiers=tuple(
                identifier
                for identifier in draft.identity_governance.identifiers
                if removed_field_key is None or identifier.field_key != removed_field_key
            ),
        ),
        mappings=tuple(mapping for mapping in draft.mappings if removed_source is None or mapping.source_field != removed_source),
        validations=draft.validations,
        schema_drift_policy=draft.schema_drift_policy,
    )
