"""Administrative routes for the isolated ingestion configuration laboratory."""

from __future__ import annotations

from functools import wraps
from datetime import date
from pathlib import Path
from typing import Any, Callable
import os
import re
import time
import uuid
from dataclasses import replace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.ingestion.configuration_contracts import (
    DRAFT_DRIFT_POLICIES,
    DRAFT_FIELD_TYPES,
    DRAFT_FORMATS,
    DRAFT_IDENTITY_ROLE_DESCRIPTIONS,
    DRAFT_IDENTITY_ROLE_LABELS,
    DRAFT_IDENTITY_ROLES,
    DRAFT_IDENTITY_STRENGTHS,
    MAX_IDENTITY_MATCH_FIELDS,
    DRAFT_TRANSFORM_DESCRIPTIONS,
    DRAFT_TRANSFORM_LABELS,
    DRAFT_TRANSFORMS,
    DRAFT_VALIDATION_KINDS,
    DraftDateTimeSettings,
    DraftFieldDefinition,
    DraftFieldSkipRule,
    DraftFieldMapping,
    DraftIdentityGovernance,
    DraftIdentityIdentifier,
    DraftReaderSettings,
    DraftRecognitionSettings,
    DraftSourceDefinition,
    DraftValidationDefinition,
)
from ...application.ingestion.configuration_service import DraftConfigurationService, suggest_source_transform
from ...application.ingestion.template_repository import TemplateRepository
from ...application.rules.configuration import RuleConfigurationService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role
from ...infrastructure.sqlite.orm import RuleCalendarVersionModel, orm_session


SESSION_KEY = "ingestion_configuration_draft"


def create_ingestion_configuration_blueprint(database_path: Path, sharepoint_root: Path | None = None) -> Blueprint:
    """Create the persisted, non-activating template configuration blueprint."""
    blueprint = Blueprint("ingestion_configuration", __name__, url_prefix="/admin/ingestion-sources")
    service = DraftConfigurationService(database_path)
    templates = TemplateRepository(database_path)
    rule_configuration = RuleConfigurationService(database_path)
    sample_artifacts: dict[str, tuple[float, str, bytes]] = {}

    def admin_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)

        return wrapped

    def approver_required(view: Callable):
        @wraps(view)
        @admin_required
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                return "Application administrator approval is required.", 403
            return view(*args, **kwargs)
        return wrapped

    def current_actor() -> str:
        return str(session.get("iam_user") or "administrator")

    def active_rule_calendar() -> dict[str, Any]:
        configuration = rule_configuration.configuration()
        context = configuration.get("context_version")
        if context is None:
            return {"available": False, "timezone": "", "calendar_id": "", "version_id": "", "label": ""}
        selected = next(
            (item for item in configuration.get("calendars", ()) if item["model"].calendar_id == context.default_calendar_id),
            None,
        )
        if selected is None:
            return {"available": False, "timezone": "", "calendar_id": "", "version_id": "", "label": ""}
        with orm_session(database_path) as database_session:
            version = database_session.get(RuleCalendarVersionModel, context.default_calendar_version_id) if context.default_calendar_version_id else None
        if version is None:
            return {"available": False, "timezone": "", "calendar_id": "", "version_id": "", "label": ""}
        return {
            "available": True,
            "timezone": str(version.timezone or context.timezone or "UTC"),
            "calendar_id": str(selected["model"].calendar_id),
            "version_id": str(version.calendar_version_id),
            "label": str(selected["model"].label or selected["model"].calendar_key),
        }

    def card_context() -> dict[str, Any]:
        cards = templates.list_template_cards()
        for card in cards:
            card["definition"] = DraftSourceDefinition.from_dict(card["definition"]).to_dict()
        return {"cards": cards, "rule_calendar": active_rule_calendar()}

    def sharepoint_folders() -> tuple[str, ...]:
        if sharepoint_root is None:
            return ()
        root = Path(sharepoint_root).expanduser().resolve()
        if not root.is_dir():
            return ()
        found: list[str] = []
        for current, directories, _files in os.walk(root, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            directories[:] = [
                name for name in directories
                if not name.startswith(".") and not (current_path / name).is_symlink() and depth < 4
            ]
            found.extend((current_path / name).relative_to(root).as_posix() for name in directories)
            if len(found) >= 500:
                found = found[:500]
                break
        return tuple(sorted(found, key=str.casefold))

    def behavior_modal(version_id: str, *, error: str | None = None, form_values=None):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        calendar = active_rule_calendar()
        date_settings = draft.date_time_settings
        if not date_settings.source_timezone and calendar["available"]:
            date_settings = replace(date_settings, source_timezone=calendar["timezone"])
        if not date_settings.target_timezone and calendar["available"]:
            date_settings = replace(date_settings, target_timezone=calendar["timezone"])
        timezone_names = tuple(sorted(available_timezones()))
        return render_template(
            "admin/_ingestion_template_behavior_modal.html",
            item=saved,
            draft=draft,
            rule_calendar=calendar,
            sharepoint_folders=sharepoint_folders(),
            timezone_names=timezone_names,
            date_settings=date_settings,
            temporal_fields=tuple(field for field in draft.fields if field.include and field.data_type.casefold() in {"date", "datetime", "timestamp"}),
            form_values=form_values,
            error=error,
        )

    def safe_sharepoint_subfolder(value: str, *, create: bool, allow_missing: bool = False) -> str:
        if sharepoint_root is None:
            raise ValueError("The configured SharePoint root is not available.")
        normalized = str(value or "").replace("\\", "/").strip()
        parts = normalized.split("/")
        if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Choose a folder below the SharePoint root using a relative path.")
        root = Path(sharepoint_root).expanduser().resolve()
        target = root.joinpath(*parts).resolve()
        if target == root or root not in target.parents:
            raise ValueError("The selected folder must remain below the SharePoint root.")
        if create:
            target.mkdir(parents=True, exist_ok=True)
        elif not target.is_dir() and not allow_missing:
            raise ValueError("Choose an existing folder or enter a new folder to create.")
        return target.relative_to(root).as_posix()

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
            identity_matching_count=_identity_matching_count(draft),
            identity_matching_limit=MAX_IDENTITY_MATCH_FIELDS,
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
                identity_matching_count=_identity_matching_count(draft),
                identity_matching_limit=MAX_IDENTITY_MATCH_FIELDS,
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
        selection = session.get("ingestion_sample_selection") or {}
        artifact = get_sample(str(selection.get("artifact_id", "")))
        if artifact is None and selection.get("artifact_id"):
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, error="The sample preview expired. Read the file again.", status_code=410)
        if artifact is None:
            inspection = _saved_template_inspection(draft)
        else:
            header_rows = _selected_header_rows(selection)
            inspection = service.inspect_sample(artifact[0], artifact[1], sheet_name=str(selection.get("sheet_name", "")), header_row=max(header_rows), header_rows=header_rows)
        errors = DraftConfigurationService.validate(draft)
        if errors:
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                artifact_id=str(selection.get("artifact_id", "")),
                error=" ".join(errors),
                status_code=400,
            )
        try:
            saved = templates.save_draft(draft.to_dict(), current_actor(), session.get("ingestion_definition_version_id"))
        except ValueError as exc:
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, artifact_id=str(selection.get("artifact_id", "")), error=str(exc), status_code=400)
        session[SESSION_KEY] = draft.to_dict()
        session["ingestion_definition_version_id"] = saved["definition_version_id"]
        return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, artifact_id=str(selection.get("artifact_id", "")), message=f"Source schema saved in this browser session and in the template library as draft version {saved['version_number']}.")

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
        errors = DraftConfigurationService.validate(draft)
        if errors:
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                artifact_id=str(selection.get("artifact_id", "")),
                error=" ".join(errors),
                status_code=400,
            )
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
            session.pop("ingestion_definition_version_id", None)
            session.pop("ingestion_sample_selection", None)
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
            try:
                saved = templates.save_draft(draft.to_dict(), current_actor(), session.get("ingestion_definition_version_id"))
            except ValueError as exc:
                return render_page(draft=draft, error=str(exc), status_code=400)
            session[SESSION_KEY] = draft.to_dict()
            session["ingestion_definition_version_id"] = saved["definition_version_id"]
            return render_page(draft=draft, message=f"Template saved to the library as draft version {saved['version_number']}.")
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

    @blueprint.get("/library")
    @admin_required
    def template_library():
        return render_template("admin/ingestion_template_library.html", **card_context())

    @blueprint.get("/library/<version_id>/identity-settings")
    @admin_required
    def identity_settings_modal(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        return render_template("admin/_ingestion_identity_settings_modal.html", item=saved, draft=draft, identity_rows=_identity_rows(draft), available_fields=tuple(field for field in draft.fields if field.include), next_identity_row_index=max(1, len(draft.identity_governance.identifiers)))

    @blueprint.get("/library/<version_id>/identity-field-row")
    @admin_required
    def identity_field_row(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        return render_template(
            "admin/_ingestion_identity_field_row.html",
            row_index=max(0, _positive_int(request.args.get("index", "0"), default=0)),
            available_fields=tuple(field for field in draft.fields if field.include),
            selected_key="",
            selected_strength="STRONG",
            selected_create=False,
        )

    @blueprint.post("/library/<version_id>/identity-settings")
    @admin_required
    def save_identity_settings(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        configured = _identity_settings_from_form(draft, request.form)
        try:
            if saved["status"] == "APPROVED":
                saved = templates.save_draft(configured.to_dict(), current_actor())
            else:
                templates.save_draft(configured.to_dict(), current_actor(), version_id)
        except ValueError as exc:
            return render_template("admin/_ingestion_identity_settings_modal.html", item=saved, draft=configured, identity_rows=_identity_rows(configured), available_fields=tuple(field for field in configured.fields if field.include), next_identity_row_index=max(1, len(configured.identity_governance.identifiers)), error=str(exc)), 400
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_ingestion_template_cards.html", **card_context(), message="Identity settings saved as a template draft.")
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.post("/library/<source_id>/move")
    @admin_required
    def move_template(source_id: str):
        try:
            cards = templates.move_template(source_id, -1 if request.form.get("direction") == "up" else 1, current_actor())
        except ValueError as exc:
            return str(exc), 404
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_ingestion_template_cards.html", **card_context())
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.get("/library/<version_id>/behavior-settings")
    @admin_required
    def behavior_settings_modal(version_id: str):
        return behavior_modal(version_id)

    @blueprint.post("/library/<version_id>/behavior-settings")
    @admin_required
    def save_behavior_settings(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        try:
            folder = str(request.form.get("folder_path", "")).strip()
            new_folder = str(request.form.get("create_folder_path", "")).strip()
            watched_subfolder = safe_sharepoint_subfolder(new_folder, create=False, allow_missing=True) if new_folder else safe_sharepoint_subfolder(folder, create=False) if folder else ""

            mode = str(request.form.get("timezone_mode", "RULE_CALENDAR")).strip().upper()
            if mode not in {"RULE_CALENDAR", "CUSTOM"}:
                raise ValueError("Choose a valid time-zone source.")
            calendar = active_rule_calendar()
            source_timezone = str(request.form.get("source_timezone", "")).strip()
            target_timezone = str(request.form.get("target_timezone", "")).strip()
            if mode == "RULE_CALENDAR" and calendar["available"]:
                source_timezone = source_timezone or calendar["timezone"]
                target_timezone = target_timezone or calendar["timezone"]
            for timezone_name in (source_timezone, target_timezone):
                if timezone_name:
                    ZoneInfo(timezone_name)
                elif mode == "CUSTOM":
                    raise ValueError("Choose both the report time zone and the time zone for date/time values.")
            valid_temporal_keys = {
                field.field_key for field in draft.fields
                if field.include and field.data_type.casefold() in {"date", "datetime", "timestamp"}
            }
            timezone_field_keys = tuple(
                key for key in request.form.getlist("timezone_field_keys")
                if key in valid_temporal_keys
            )
            date_time_settings = DraftDateTimeSettings(
                timezone_mode=mode,
                source_timezone=source_timezone,
                target_timezone=target_timezone,
                calendar_id=calendar["calendar_id"] if calendar["available"] else "",
                calendar_version_id=calendar["version_id"] if calendar["available"] else "",
                calendar_label=calendar["label"] if calendar["available"] else "",
                field_keys=timezone_field_keys,
            )

            skip_field_key = str(request.form.get("skip_field_key", "")).strip()
            skip_rules: tuple[DraftFieldSkipRule, ...] = ()
            if skip_field_key:
                if skip_field_key not in valid_temporal_keys:
                    raise ValueError("Choose an included date or date/time field for the restriction.")
                condition = str(request.form.get("skip_condition", "")).strip().upper()
                if condition not in {"BEFORE", "AFTER", "ON_OR_BEFORE", "ON_OR_AFTER"}:
                    raise ValueError("Choose how the date field should be compared.")
                comparison_value = str(request.form.get("skip_comparison_value", "")).strip()
                try:
                    comparison_value = date.fromisoformat(comparison_value).isoformat()
                except ValueError as exc:
                    raise ValueError("Choose a valid comparison date.") from exc
                skip_rules = (DraftFieldSkipRule(field_key=skip_field_key, condition=condition, comparison_value=comparison_value),)

            configured = replace(
                draft,
                watched_subfolder=watched_subfolder,
                date_time_settings=date_time_settings,
                skip_rules=skip_rules,
            )
            if new_folder:
                safe_sharepoint_subfolder(new_folder, create=True)
            if saved["status"] == "APPROVED":
                templates.save_draft(configured.to_dict(), current_actor())
            else:
                templates.save_draft(configured.to_dict(), current_actor(), version_id)
        except (ValueError, OSError, ZoneInfoNotFoundError) as exc:
            response = behavior_modal(version_id, error=str(exc), form_values=request.form)
            return response, 400
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_ingestion_template_cards.html", **card_context(), message="Template settings saved.")
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.get("/new")
    @admin_required
    def start_new_template():
        session.pop(SESSION_KEY, None)
        session.pop("ingestion_definition_version_id", None)
        session.pop("ingestion_sample_selection", None)
        return redirect(url_for("ingestion_configuration.configuration_page"))

    @blueprint.get("/library/<version_id>/edit")
    @admin_required
    def edit_saved_draft(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        if saved["status"] != "DRAFT":
            return redirect(url_for("ingestion_configuration.create_version", version_id=version_id))
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        session[SESSION_KEY] = draft.to_dict()
        session["ingestion_definition_version_id"] = version_id
        session.pop("ingestion_sample_selection", None)
        return render_page(draft=draft, inspection=_saved_template_inspection(draft), message=f"Editing saved draft version {saved['version_number']}.")

    @blueprint.post("/library/<version_id>/approve")
    @approver_required
    def approve_template(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        errors = DraftConfigurationService.validate(DraftSourceDefinition.from_dict(saved["definition"]))
        if errors:
            return render_template("admin/ingestion_template_library.html", **card_context(), error=" ".join(errors)), 400
        try:
            templates.approve(version_id, current_actor())
        except ValueError as exc:
            return render_template("admin/ingestion_template_library.html", **card_context(), error=str(exc)), 409
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.post("/library/<version_id>/new-version")
    @admin_required
    def create_version(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        if saved["status"] != "APPROVED":
            return redirect(url_for("ingestion_configuration.edit_saved_draft", version_id=version_id))
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        version = templates.save_draft(draft.to_dict(), current_actor())
        session[SESSION_KEY] = draft.to_dict()
        session["ingestion_definition_version_id"] = version["definition_version_id"]
        session.pop("ingestion_sample_selection", None)
        return render_page(draft=draft, inspection=_saved_template_inspection(draft), message=f"New draft version {version['version_number']} created from approved version {saved['version_number']}.")

    return blueprint


def _saved_template_inspection(draft: DraftSourceDefinition) -> dict[str, Any]:
    headers = tuple(field.source_name for field in draft.fields)
    return {
        "filename": "Saved template",
        "format": draft.reader_settings.format,
        "sheet_names": (draft.reader_settings.sheet_name,) if draft.reader_settings.sheet_name else (),
        "selected_sheet": draft.reader_settings.sheet_name,
        "header_rows": draft.reader_settings.header_rows,
        "headers": headers,
        "rows_detected": 0,
        "rows": (),
        "saved_template": True,
    }


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
    temporal_field_keys = {
        field.field_key for field in fields
        if field.include and field.data_type.casefold() in {"date", "datetime", "timestamp"}
    }
    return replace(
        _draft_with_source_basics(draft, {}, filename),
        fields=fields,
        date_time_settings=replace(
            draft.date_time_settings,
            field_keys=tuple(key for key in draft.date_time_settings.field_keys if key in temporal_field_keys),
        ),
        skip_rules=tuple(rule for rule in draft.skip_rules if rule.field_key in temporal_field_keys),
        reader_settings=replace(draft.reader_settings, format=str(inspection.get("format", "XLSX")), sheet_name=str(inspection.get("selected_sheet", "")), header_row=max(tuple(inspection.get("header_rows", (1,)))), header_rows=tuple(inspection.get("header_rows", (1,)))),
        recognition_settings=replace(draft.recognition_settings, extension=".csv" if inspection.get("format") == "CSV" else ".xlsx", sheet_name=str(inspection.get("selected_sheet", "")), required_headers=tuple(str(header) for header in inspection.get("headers", ()))),
        # The configuration laboratory describes source schema only. Canonical
        # or employee mappings are intentionally deferred to the Employee Engine.
        mappings=(),
    )


def _draft_from_mapping_form(draft: DraftSourceDefinition, form) -> DraftSourceDefinition:
    legacy_identity_post = form.get("identity_role") is not None
    fields = []
    for index, field in enumerate(draft.fields):
        legacy_identity_selected = legacy_identity_post and (
            form.get(f"identity_field_{index}_match") == "on"
            or form.get(f"identity_field_{index}_create") == "on"
        )
        fields.append(replace(
            field,
            include=form.get(f"field_include_{index}") == "on",
            field_key=str(form.get(f"field_key_{index}", field.field_key)).strip() or field.field_key,
            data_type=("string" if legacy_identity_selected else str(form.get(f"field_type_{index}", field.data_type)).strip() or field.data_type),
            identifier=legacy_identity_selected,
            transform_name=str(form.get(f"field_transform_{index}", field.transform_name)).strip() or field.transform_name,
        ))
    fields = tuple(fields)
    fields_by_key = {field.field_key.casefold(): field for field in fields if field.include}
    identifiers = tuple(
        replace(identifier, field_key=fields_by_key[identifier.field_key.casefold()].field_key)
        for identifier in draft.identity_governance.identifiers
        if identifier.field_key.casefold() in fields_by_key
    )
    identity_governance = _identity_governance_from_form(draft, fields, form) if legacy_identity_post else replace(draft.identity_governance, identifiers=identifiers)
    identifier_keys = {item.field_key.casefold() for item in identity_governance.identifiers}
    fields = tuple(
        replace(field, identifier=field.field_key.casefold() in identifier_keys,
                data_type="string" if field.field_key.casefold() in identifier_keys else field.data_type)
        for field in fields
    )
    temporal_field_keys = {
        field.field_key for field in fields
        if field.include and field.data_type.casefold() in {"date", "datetime", "timestamp"}
    }
    return replace(
        _draft_with_source_basics(draft, form, draft.reader_settings.filename_pattern or draft.display_name),
        fields=fields,
        identity_governance=identity_governance,
        date_time_settings=replace(
            draft.date_time_settings,
            field_keys=tuple(key for key in draft.date_time_settings.field_keys if key in temporal_field_keys),
        ),
        skip_rules=tuple(rule for rule in draft.skip_rules if rule.field_key in temporal_field_keys),
        mappings=(),
    )


def _identity_settings_from_form(draft: DraftSourceDefinition, form) -> DraftSourceDefinition:
    role = str(form.get("identity_role", "EVIDENCE_ONLY")).strip().upper()
    if role not in DRAFT_IDENTITY_ROLES:
        role = "EVIDENCE_ONLY"
    can_create_employee = role == "IDENTITY_SEED" and form.get("identity_can_create_employee") == "on"
    identifiers: list[DraftIdentityIdentifier] = []
    fields: list[DraftFieldDefinition] = []
    field_by_key = {field.field_key.casefold(): field for field in draft.fields if field.include}
    used_keys: set[str] = set()
    for raw_index in form.getlist("identity_row_indices"):
        index = _positive_int(raw_index, default=0)
        field_key = str(form.get(f"identity_field_{index}_key", "")).strip()
        identity_field = field_by_key.get(field_key.casefold())
        if identity_field is None or role == "EVIDENCE_ONLY" or field_key.casefold() in used_keys:
            continue
        used_keys.add(field_key.casefold())
        strength = str(form.get(f"identity_field_{index}_strength", "STRONG")).strip().upper()
        if strength not in DRAFT_IDENTITY_STRENGTHS:
            strength = "STRONG"
        can_create_identity = can_create_employee and strength == "STRONG" and form.get(f"identity_field_{index}_create") == "on"
        identifiers.append(DraftIdentityIdentifier(field_key=identity_field.field_key, strength=strength, can_match=True, can_create_identity=can_create_identity))
    selected_keys = {identifier.field_key.casefold() for identifier in identifiers}
    for field in draft.fields:
        selected = field.include and field.field_key.casefold() in selected_keys
        fields.append(replace(field, identifier=selected, data_type="string" if selected else field.data_type))
    return replace(
        draft,
        fields=tuple(fields),
        identity_governance=DraftIdentityGovernance(
            role=role,
            can_create_employee=can_create_employee,
            identifiers=tuple(identifiers),
        ),
        status="DRAFT",
    )


def _identity_rows(draft: DraftSourceDefinition) -> tuple[dict[str, Any], ...]:
    rows = tuple(
        {"index": index, "field_key": item.field_key, "strength": item.strength, "can_create_identity": item.can_create_identity}
        for index, item in enumerate(draft.identity_governance.identifiers)
        if item.can_match
    )
    return rows or ({"index": 0, "field_key": "", "strength": "STRONG", "can_create_identity": False},)


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
        if role != "IDENTITY_SEED" or not can_create_employee or not can_match:
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


def _identity_matching_count(draft: DraftSourceDefinition) -> int:
    return sum(1 for item in draft.identity_governance.identifiers if item.can_match)


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
        watched_subfolder=draft.watched_subfolder,
        date_time_settings=draft.date_time_settings,
        skip_rules=draft.skip_rules,
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
        watched_subfolder=draft.watched_subfolder,
        date_time_settings=replace(
            draft.date_time_settings,
            field_keys=tuple(key for key in draft.date_time_settings.field_keys if removed_field_key is None or key != removed_field_key),
        ),
        skip_rules=tuple(rule for rule in draft.skip_rules if removed_field_key is None or rule.field_key != removed_field_key),
        mappings=tuple(mapping for mapping in draft.mappings if removed_source is None or mapping.source_field != removed_source),
        validations=draft.validations,
        schema_drift_policy=draft.schema_drift_policy,
    )
