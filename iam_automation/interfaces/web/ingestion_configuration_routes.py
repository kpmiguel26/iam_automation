"""Administrative routes for the isolated ingestion configuration laboratory."""

from __future__ import annotations

from functools import wraps
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import replace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from flask import Blueprint, flash, make_response, redirect, render_template, request, session, url_for
from sqlalchemy import select

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
from ...application.ingestion.object_template_repository import ObjectTemplateRepository
from ...application.ingestion.template_repository import TemplateRepository
from ...application.parallel_engine.templates import RuntimeTemplateCatalog
from ...application.rules.configuration import RuleConfigurationService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role
from ...infrastructure.sqlite.orm import DimSourceModel, RuleCalendarVersionModel, orm_session


SESSION_KEY = "ingestion_configuration_draft"


def _display_metadata(value: object) -> str:
    """Decode source-provided HTML entities for display without changing stored keys."""
    return unescape(str(value or "")).strip()


def create_ingestion_configuration_blueprint(database_path: Path, sharepoint_root: Path | None = None) -> Blueprint:
    """Create the persisted, non-activating template configuration blueprint."""
    blueprint = Blueprint("ingestion_configuration", __name__, url_prefix="/admin/ingestion-sources")
    service = DraftConfigurationService(database_path)
    templates = TemplateRepository(database_path)
    object_templates = ObjectTemplateRepository(database_path)
    object_template_catalog = (
        RuntimeTemplateCatalog(database_path, sharepoint_root)
        if sharepoint_root is not None else None
    )
    rule_configuration = RuleConfigurationService(database_path)
    sample_artifacts: dict[str, tuple[float, str, bytes]] = {}

    def rule_source_systems() -> tuple[dict[str, str], ...]:
        with orm_session(database_path) as db_session:
            return tuple({"key": str(system), "label": str(label or system)} for system, label in db_session.execute(
                select(DimSourceModel.source_system, DimSourceModel.label)
                .where(DimSourceModel.active.is_(True))
                .order_by(DimSourceModel.label.asc(), DimSourceModel.source_system.asc())
            ).all())

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

    def fragment_status(status_code: int) -> int:
        """Let HTMX swap rendered validation feedback while preserving HTTP errors for normal forms."""
        if request.headers.get("HX-Request") == "true" and 400 <= status_code < 500:
            return 200
        return status_code

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
        property_options: list[dict[str, str]] = []
        identity_options: list[dict[str, Any]] = []
        object_sources: list[dict[str, Any]] = []
        for card in cards:
            card["definition"] = DraftSourceDefinition.from_dict(card["definition"]).to_dict()
            # Object templates pin approved report snapshots. Keep library cards
            # on their current draft, but derive object choices from the latest
            # approved snapshot so a draft cannot create an unapprovable object.
            approved_version = next(
                (version for version in card.get("versions", ()) if version.get("status") == "APPROVED"),
                card if card.get("status") == "APPROVED" else None,
            )
            if approved_version is None:
                continue
            approved_definition = DraftSourceDefinition.from_dict(approved_version["definition"]).to_dict()
            included_fields = [field for field in approved_definition["fields"] if field["include"]]
            object_sources.append({
                "source_id": card["source_id"],
                "source_definition_version_id": approved_version["definition_version_id"],
                "version_number": approved_version["version_number"],
                "source_label": approved_definition["display_name"] or card["source_id"],
                "field_count": len(included_fields),
                "ingestion_order": card["ingestion_order"],
            })
            for field in included_fields:
                property_options.append({
                    "source_id": card["source_id"],
                    "source_definition_version_id": approved_version["definition_version_id"],
                    "source_label": approved_definition["display_name"] or card["source_id"],
                    "field_key": field["field_key"],
                    "source_name": field["source_name"],
                    "data_type": field["data_type"],
                    "value": json.dumps([card["source_id"], field["field_key"]], ensure_ascii=False),
                })
            identity = approved_definition["identity_governance"]
            included_by_key = {field["field_key"]: field for field in included_fields}
            for identifier in identity["identifiers"]:
                field = included_by_key.get(identifier["field_key"])
                if not field or not identifier["can_match"]:
                    continue
                identity_options.append({
                    "source_id": card["source_id"],
                    "source_definition_version_id": approved_version["definition_version_id"],
                    "source_label": approved_definition["display_name"] or card["source_id"],
                    "field_key": identifier["field_key"],
                    "source_name": field["source_name"],
                    "strength": identifier["strength"],
                    "can_create_identity": identifier["can_create_identity"],
                    "source_can_create_object": identity["role"] == "IDENTITY_SEED" and identity["can_create_employee"],
                    "value": json.dumps([card["source_id"], identifier["field_key"]], ensure_ascii=False),
                })
        for option in property_options + identity_options:
            option["display_source_name"] = _display_metadata(option.get("source_name")) or "Unnamed field"
            option["display_field_key"] = _display_metadata(option.get("field_key")) or "Unnamed field"
        property_options.sort(key=lambda option: (option["source_label"].casefold(), option["source_name"].casefold()))
        identity_options.sort(key=lambda option: (option["source_label"].casefold(), option["source_name"].casefold()))
        object_sources.sort(key=lambda option: (option["ingestion_order"], option["source_label"].casefold()))
        return {
            "cards": cards,
            "rule_calendar": active_rule_calendar(),
            "object_template": object_templates.latest(),
            "object_sources": object_sources,
            "object_property_options": property_options,
            "object_identity_options": identity_options,
            "can_approve_object_template": bool(
                {normalize_role(role) for role in session.get("iam_roles", ())}
                & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}
            ),
        }

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

    def sharepoint_folder_tree(folders: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        """Build a nested presentation tree from the safe relative folder list."""
        roots: list[dict[str, object]] = []
        for folder in folders:
            parts = folder.split("/")
            siblings = roots
            current_path: list[str] = []
            for part in parts:
                current_path.append(part)
                relative_path = "/".join(current_path)
                node = next((item for item in siblings if item["name"] == part), None)
                if node is None:
                    node = {"name": part, "path": relative_path, "children": []}
                    siblings.append(node)
                siblings = node["children"]
        return tuple(roots)

    def render_template_settings_page(
        version_id: str, *, error: str | None = None, form_values=None,
        configured: DraftSourceDefinition | None = None,
    ):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = configured or DraftSourceDefinition.from_dict(saved["definition"])
        calendar = active_rule_calendar()
        date_settings = draft.date_time_settings
        if not date_settings.source_timezone and calendar["available"]:
            date_settings = replace(date_settings, source_timezone=calendar["timezone"])
        if not date_settings.target_timezone and calendar["available"]:
            date_settings = replace(date_settings, target_timezone=calendar["timezone"])
        timezone_names = tuple(sorted(available_timezones()))
        folder_paths = sharepoint_folders()
        return render_template(
            "admin/ingestion_template_settings.html",
            item=saved,
            draft=draft,
            rule_source_systems=rule_source_systems(),
            identity_rows=_identity_rows(draft),
            available_fields=tuple(field for field in draft.fields if field.include),
            next_identity_row_index=max(1, len(draft.identity_governance.identifiers)),
            rule_calendar=calendar,
            sharepoint_folders=folder_paths,
            sharepoint_folder_tree=sharepoint_folder_tree(folder_paths),
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
            rule_source_systems=rule_source_systems(),
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
            identity_matching_limit=draft.identity_governance.max_matching_fields,
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
                rule_source_systems=rule_source_systems(),
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
                identity_matching_limit=draft.identity_governance.max_matching_fields,
                identity_identifier_by_field={item.field_key: item for item in draft.identity_governance.identifiers},
                identity_recommendations={field.field_key: _identity_recommendation(field) for field in draft.fields},
                validation_kinds=DRAFT_VALIDATION_KINDS,
                drift_policies=DRAFT_DRIFT_POLICIES,
                raw_column_count=_raw_column_count(context.get("raw_rows", ())),
                **context,
            ), fragment_status(status_code)
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
        action = str(request.form.get("action", "validate")).strip().lower()
        if action not in {"validate", "save"}:
            action = "validate"
        draft = _draft_from_mapping_form(DraftSourceDefinition.from_dict(session.get(SESSION_KEY)), request.form)
        configured_rule_sources = {item["key"] for item in rule_source_systems()}
        if draft.business_rule_source_system and draft.business_rule_source_system not in configured_rule_sources:
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html", draft=draft,
                error="Choose an active Business Rules source or leave the source mapping blank.",
                status_code=400,
            )
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
            session.pop("ingestion_template_validation", None)
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                artifact_id=str(selection.get("artifact_id", "")),
                error=" ".join(errors),
                status_code=400,
            )
        sample_checks = service.preview(draft, inspection)
        blocking_sample_checks = [
            diagnostic for diagnostic in sample_checks["diagnostics"]
            if diagnostic["severity"] == "BLOCKING"
        ]
        if blocking_sample_checks:
            session.pop("ingestion_template_validation", None)
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                preview=sample_checks,
                artifact_id=str(selection.get("artifact_id", "")),
                error="This sample fails runtime checks. Resolve the blocking header or field-type issues before saving this draft.",
                status_code=400,
            )
        validation_fingerprint = hashlib.sha256(json.dumps(
            {"draft": draft.to_dict(), "selection": selection},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()
        if action == "validate":
            session[SESSION_KEY] = draft.to_dict()
            session["ingestion_template_validation"] = validation_fingerprint
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                preview=sample_checks,
                artifact_id=str(selection.get("artifact_id", "")),
                validation_passed=True,
                message="Validation passed. Review the checks, then choose Save template.",
            )
        if session.get("ingestion_template_validation") != validation_fingerprint:
            session.pop("ingestion_template_validation", None)
            session[SESSION_KEY] = draft.to_dict()
            return partial_or_page(
                "admin/_ingestion_sample_mapping.html",
                draft=draft,
                inspection=inspection,
                preview=sample_checks,
                artifact_id=str(selection.get("artifact_id", "")),
                error="This template changed after validation. Validate it again before saving.",
                status_code=400,
            )
        try:
            saved = templates.save_draft(draft.to_dict(), current_actor(), session.get("ingestion_definition_version_id"))
        except ValueError as exc:
            return partial_or_page("admin/_ingestion_sample_mapping.html", draft=draft, inspection=inspection, preview=sample_checks, artifact_id=str(selection.get("artifact_id", "")), error=f"Could not save the report template: {exc}", status_code=400)
        session[SESSION_KEY] = draft.to_dict()
        session["ingestion_definition_version_id"] = saved["definition_version_id"]
        session.pop("ingestion_template_validation", None)
        if saved.get("reactivated"):
            message = f"The deleted report template was restored as draft version {saved['version_number']}. Its earlier versions and audit history were retained."
        else:
            message = f"Template saved to the library as draft version {saved['version_number']}."
        flash(message, "success")
        library_url = url_for("ingestion_configuration.template_library")
        if request.headers.get("HX-Request") == "true":
            response = make_response("", 200)
            response.headers["HX-Redirect"] = library_url
            return response
        return redirect(library_url)

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
            flash(f"Template saved to the library as draft version {saved['version_number']}.", "success")
            return redirect(url_for("ingestion_configuration.template_library"))
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

    @blueprint.get("/library/<source_id>/delete")
    @admin_required
    def delete_template_modal(source_id: str):
        item = next((card for card in templates.list_template_cards() if card["source_id"] == source_id), None)
        if item is None:
            return "Report template not found.", 404
        impact = templates.deletion_impact(source_id)
        return render_template("admin/_ingestion_delete_template_modal.html", item=item, impact=impact)

    @blueprint.post("/library/<source_id>/delete")
    @admin_required
    def delete_template(source_id: str):
        try:
            templates.delete_template(source_id, current_actor())
        except ValueError as exc:
            message = str(exc)
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_ingestion_template_cards.html", **card_context(), error=message)
            return render_template("admin/ingestion_template_library.html", **card_context(), error=message), 409
        message = "The template was removed from the active library. Imported evidence and version history were retained."
        if request.headers.get("HX-Request") == "true":
            return render_template(
                "admin/_ingestion_template_cards.html",
                **card_context(),
                message=message,
            )
        return redirect(url_for("ingestion_configuration.template_library"))

    def parse_object_ref(value: str) -> tuple[str, str] | None:
        try:
            source_id, field_key = json.loads(value)
        except (TypeError, ValueError):
            return None
        if not source_id or not field_key:
            return None
        return str(source_id), str(field_key)

    def object_template_context(form_values=None, *, error: str | None = None, partial: bool = False):
        context = card_context()
        saved = context["object_template"]
        prior_definition = (saved or {}).get("definition", {})
        sources = list(context["object_sources"])
        source_ids = {source["source_id"] for source in sources}
        for source in prior_definition.get("source_templates", ()):
            source_id = str(source.get("source_id", ""))
            if source_id and source_id not in source_ids:
                sources.append({**source, "stale": True, "field_count": 0})
                source_ids.add(source_id)
        identity_options = list(context["object_identity_options"])
        identity_refs = {(item["source_id"], item["field_key"]) for item in identity_options}
        for identifier in prior_definition.get("identifiers", ()):
            key = (str(identifier.get("source_id", "")), str(identifier.get("field_key", "")))
            if key[0] and key[1] and key not in identity_refs:
                identity_options.append({**identifier, "source_label": identifier.get("source_label", key[0]), "stale": True, "value": json.dumps(list(key), ensure_ascii=False)})
                identity_refs.add(key)
        property_options = list(context["object_property_options"])
        property_refs = {(item["source_id"], item["field_key"]) for item in property_options}
        prior_properties_by_ref = {
            (str(item.get("source_id", "")), str(item.get("field_key", ""))): item
            for item in prior_definition.get("properties", ())
        }
        property_options = [
            {
                **item,
                "canonical_property_key": str(
                    prior_properties_by_ref.get((item["source_id"], item["field_key"]), {}).get(
                        "canonical_property_key", item["field_key"]
                    )
                ),
            }
            for item in property_options
        ]
        for prop in prior_definition.get("properties", ()):
            key = (str(prop.get("source_id", "")), str(prop.get("field_key", "")))
            if key[0] and key[1] and key not in property_refs:
                property_options.append({
                    **prop,
                    "canonical_property_key": str(prop.get("canonical_property_key") or key[1]),
                    "source_label": prop.get("source_label", key[0]),
                    "stale": True,
                })
                property_refs.add(key)

        for option in property_options + identity_options:
            option["display_source_name"] = _display_metadata(option.get("source_name")) or "Unnamed field"
            option["display_field_key"] = _display_metadata(option.get("field_key")) or "Unnamed field"

        if form_values is not None:
            posted_source_ids = form_values.getlist("property_source_ids")
            posted_field_keys = form_values.getlist("property_field_keys")
            posted_canonical_keys = form_values.getlist("canonical_property_keys")
            posted_canonical_by_ref = {
                (str(source_id), str(field_key)): str(canonical_key)
                for source_id, field_key, canonical_key in zip(
                    posted_source_ids, posted_field_keys, posted_canonical_keys
                )
            }
            property_options = [
                {
                    **item,
                    "canonical_property_key": posted_canonical_by_ref.get(
                        (item["source_id"], item["field_key"]), item["canonical_property_key"]
                    ),
                }
                for item in property_options
            ]
            selected_sources = set(form_values.getlist("object_sources"))
            selected_identifiers = {ref for value in form_values.getlist("object_identifiers") if (ref := parse_object_ref(value))}
            title_property_key = str(form_values.get("title_property_key", "")).strip()
            context_property_keys = list(dict.fromkeys(
                str(value).strip() for value in form_values.getlist("context_property_keys") if str(value).strip()
            ))
            object_name = str(form_values.get("object_name", ""))
            creation_authorized = form_values.get("allow_object_creation") == "on"
            indices = form_values.getlist("object_match_indices")
            matches = []
            for index in indices:
                index = _positive_int(index, default=0)
                if any(item["index"] == index for item in matches):
                    continue
                source_id = str(form_values.get(f"object_match_source_{index}", ""))
                anchor_value = str(form_values.get(f"object_match_anchor_{index}", ""))
                target_values = [str(value) for value in form_values.getlist(f"object_match_targets_{index}") if value]
                matches.append({
                    "index": index,
                    "source_id": source_id,
                    "anchor_value": anchor_value,
                    "target_values": target_values,
                })
        else:
            saved_sources = prior_definition.get("source_templates", ())
            selected_sources = {str(source.get("source_id", "")) for source in saved_sources if source.get("source_id")}
            if not saved_sources:
                selected_sources = {source["source_id"] for source in context["object_sources"]}
            selected_identifiers = {
                (str(item.get("source_id", "")), str(item.get("field_key", "")))
                for item in prior_definition.get("identifiers", ())
                if item.get("source_id") and item.get("field_key")
            }
            presentation = prior_definition.get("presentation", {})
            title_property_key = str(presentation.get("title_property_key", ""))
            context_property_keys = list(presentation.get("context_property_keys", ()))
            object_name = str(prior_definition.get("object_name", ""))
            creation_authorized = bool(prior_definition.get("allow_object_creation", False))
            matches = []
            grouped_matches: dict[tuple[str, str], dict[str, Any]] = {}
            for match in prior_definition.get("matches", ()):
                left = match.get("left", {})
                right = match.get("right", {})
                anchor_ref = (str(left.get("source_id", "")), str(left.get("field_key", "")))
                target_ref = (str(right.get("source_id", "")), str(right.get("field_key", "")))
                if not all(anchor_ref) or not all(target_ref):
                    continue
                group = grouped_matches.setdefault(anchor_ref, {
                    "source_id": anchor_ref[0],
                    "anchor_value": json.dumps(list(anchor_ref), ensure_ascii=False),
                    "target_values": [],
                })
                target_value = json.dumps(list(target_ref), ensure_ascii=False)
                if target_value not in group["target_values"]:
                    group["target_values"].append(target_value)
            matches = [dict(item, index=index) for index, item in enumerate(grouped_matches.values())]
        sources.sort(key=lambda item: (int(item.get("ingestion_order", 2147483647)), str(item.get("source_label", item.get("source_id", ""))).casefold()))
        identity_options.sort(key=lambda item: (str(item.get("source_label", "")).casefold(), str(item.get("source_name", "")).casefold()))
        property_options.sort(key=lambda item: (str(item.get("source_label", "")).casefold(), str(item.get("source_name", "")).casefold()))
        display_identity_refs = {
            (item["source_id"], item["field_key"])
            for item in identity_options
            if item.get("strength") in {"STRONG", "SUPPORTING"}
            and (item["source_id"], item["field_key"]) in selected_identifiers
        }
        display_options_by_key = {}
        for prop in property_options:
            ref = (prop["source_id"], prop["field_key"])
            key = str(prop.get("canonical_property_key") or prop["field_key"])
            if ref not in display_identity_refs or prop["source_id"] not in selected_sources:
                continue
            option = display_options_by_key.setdefault(key, {"key": key, "sources": []})
            source_name = str(prop.get("source_label") or prop["source_id"])
            if source_name not in option["sources"]:
                option["sources"].append(source_name)
        display_options = [
            {**item, "display_key": _display_metadata(item["key"]) or "Unnamed field",
             "sources": [_display_metadata(source) or source for source in item["sources"]],
             "source_summary": ", ".join(_display_metadata(source) or source for source in item["sources"])}
            for item in sorted(display_options_by_key.values(), key=lambda item: item["key"].casefold())
        ]
        display_option_keys = {item["key"] for item in display_options}
        if title_property_key not in display_option_keys:
            title_property_key = ""
        context_property_keys = [key for key in context_property_keys if key in display_option_keys and key != title_property_key]
        return render_template(
            "admin/_object_template_presentation_fields.html" if partial else "admin/ingestion_object_template_settings.html",
            object_sources=sources,
            identity_options=identity_options,
            property_options=property_options,
            display_options=display_options,
            title_property_key=title_property_key,
            context_property_keys=context_property_keys,
            selected_sources=selected_sources,
            selected_identifiers=selected_identifiers,
            next_match_index=max((int(item["index"]) for item in matches), default=-1) + 1,
            object_name=object_name,
            creation_authorized=creation_authorized,
            matches=matches,
            saved=saved,
            error=error,
        )

    def object_template_error(form_values, message: str):
        return object_template_context(form_values, error=message), 400

    @blueprint.get("/library/template-object/settings", endpoint="object_template_settings_page")
    @blueprint.get("/library/template-object/settings", endpoint="object_template_modal")
    @admin_required
    def object_template_settings_page():
        return object_template_context()

    @blueprint.get("/library/template-object/presentation-fields")
    @admin_required
    def object_template_presentation_fields():
        return object_template_context(request.args, partial=True)

    @blueprint.get("/library/template-object/match-row")
    @admin_required
    def object_template_match_row():
        context = card_context()
        selected_sources = set(request.args.getlist("object_sources"))
        selected_refs = {ref for value in request.args.getlist("object_identifiers") if (ref := parse_object_ref(value))}
        selected_strong = [
            item for item in context["object_identity_options"]
            if item["strength"] == "STRONG" and item["source_id"] in selected_sources
            and (item["source_id"], item["field_key"]) in selected_refs
        ]
        strong_sources = {item["source_id"] for item in selected_strong}
        if len(strong_sources) < 2:
            return "", 204
        return render_template(
            "admin/_object_template_match_row.html",
            row_index=_positive_int(request.args.get("index", "0"), default=0),
            object_sources=[item for item in context["object_sources"] if item["source_id"] in selected_sources],
            identity_options=selected_strong,
            selected_sources=selected_sources,
            selected_identifiers=selected_refs,
            match={"source_id": "", "anchor_value": "", "target_values": []},
        )

    @blueprint.post("/library/template-object/settings")
    @admin_required
    def save_object_template():
        context = card_context()
        prior = context["object_template"]
        prior_definition = (prior or {}).get("definition", {})
        current_sources = {item["source_id"]: item for item in context["object_sources"]}
        prior_sources = {str(item.get("source_id", "")): item for item in prior_definition.get("source_templates", ())}
        selected_sources = list(dict.fromkeys(request.form.getlist("object_sources")))
        source_refs = {**prior_sources, **current_sources}
        object_name = str(request.form.get("object_name", "")).strip()
        if not object_name:
            return object_template_error(request.form, "Enter a name for this object template.")
        if len(object_name) > 120:
            return object_template_error(request.form, "Keep the object name to 120 characters or fewer.")
        if not selected_sources or any(source_id not in source_refs for source_id in selected_sources):
            return object_template_error(request.form, "Choose at least one saved report template for this object.")
        unavailable_sources = [source_id for source_id in selected_sources if source_id not in current_sources]
        if unavailable_sources:
            return object_template_error(
                request.form,
                "Remove report sources without a current approved version, then select approved sources from the library.",
            )

        identity_options = {(item["source_id"], item["field_key"]): item for item in context["object_identity_options"]}
        prior_identities = {
            (str(item.get("source_id", "")), str(item.get("field_key", ""))): item
            for item in prior_definition.get("identifiers", ())
        }
        selected_identifiers: list[dict[str, Any]] = []
        seen_identifier_refs: set[tuple[str, str]] = set()
        for value in request.form.getlist("object_identifiers"):
            ref = parse_object_ref(value)
            if not ref or ref[0] not in selected_sources or ref in seen_identifier_refs:
                continue
            candidate = identity_options.get(ref) or prior_identities.get(ref)
            if candidate is None:
                return object_template_error(request.form, "Choose only strong or weak identifiers configured in the selected report templates.")
            current_source = current_sources.get(ref[0])
            if (
                current_source is not None
                and candidate.get("source_definition_version_id")
                and candidate.get("source_definition_version_id") != current_source.get("source_definition_version_id")
            ):
                return object_template_error(
                    request.form,
                    f"Refresh the identifier selection for {current_source['source_label']}; its approved report version changed.",
                )
            if current_source is None:
                return object_template_error(request.form, "The selected identifier no longer has an approved report source.")
            selected_identifiers.append(candidate)
            seen_identifier_refs.add(ref)

        selected_identity_map = {(item["source_id"], item["field_key"]): item for item in selected_identifiers}
        if not selected_identifiers:
            return object_template_error(request.form, "Choose at least one configured Strong or Supporting identifier for this object.")
        match_indices = list(dict.fromkeys(_positive_int(value, default=0) for value in request.form.getlist("object_match_indices")))
        matches: list[dict[str, Any]] = []
        used_match_pairs: set[frozenset[tuple[str, str]]] = set()
        adjacency = {source_id: set() for source_id in selected_sources}
        for index in match_indices:
            source_id = str(request.form.get(f"object_match_source_{index}", ""))
            anchor_value = str(request.form.get(f"object_match_anchor_{index}", ""))
            target_values = [str(value) for value in request.form.getlist(f"object_match_targets_{index}") if value]
            if not source_id and not anchor_value and not target_values:
                continue
            anchor_ref = parse_object_ref(anchor_value)
            anchor = selected_identity_map.get(anchor_ref) if anchor_ref else None
            if source_id not in selected_sources or anchor is None or anchor["strength"] != "STRONG" or anchor["source_id"] != source_id:
                return object_template_error(request.form, "Choose a selected Strong identifier from the selected anchor report.")
            if not target_values:
                return object_template_error(request.form, "Choose at least one Strong identifier from another report for each match group.")
            for target_value in target_values:
                target_ref = parse_object_ref(target_value)
                target = selected_identity_map.get(target_ref) if target_ref else None
                if target is None or target["strength"] != "STRONG":
                    return object_template_error(request.form, "Each target must be a selected Strong identifier.")
                if target["source_id"] == source_id:
                    return object_template_error(request.form, "Choose target identifiers from reports other than the anchor report.")
                pair_ref = frozenset((anchor_ref, target_ref))
                if pair_ref in used_match_pairs:
                    return object_template_error(request.form, "This Strong identifier pair is already included in another match group.")
                used_match_pairs.add(pair_ref)
                adjacency[anchor["source_id"]].add(target["source_id"])
                adjacency[target["source_id"]].add(anchor["source_id"])
                matches.append({"strength": "STRONG", "left": anchor, "right": target})

        if len(selected_sources) > 1:
            sources_with_strong_ids = {item["source_id"] for item in selected_identifiers if item["strength"] == "STRONG"}
            if any(source_id not in sources_with_strong_ids for source_id in selected_sources):
                return object_template_error(request.form, "Choose a Strong identifier for every report template that contributes fields.")
            connected = set()
            frontier = [selected_sources[0]]
            while frontier:
                source_id = frontier.pop()
                if source_id in connected:
                    continue
                connected.add(source_id)
                frontier.extend(adjacency.get(source_id, ()) - connected)
            if connected != set(selected_sources):
                return object_template_error(request.form, "Link every contributing report template through Strong identifiers before saving.")
            selected_library_sources = [current_sources[source_id] for source_id in selected_sources if source_id in current_sources]
            if selected_library_sources and match_indices:
                first_source = min(selected_library_sources, key=lambda item: (int(item["ingestion_order"]), str(item["source_id"])))
                first_anchor_source = next((
                    str(request.form.get(f"object_match_source_{index}", ""))
                    for index in match_indices
                    if request.form.get(f"object_match_source_{index}")
                    or request.form.get(f"object_match_anchor_{index}")
                    or request.form.getlist(f"object_match_targets_{index}")
                ), "")
                if first_anchor_source != first_source["source_id"]:
                    return object_template_error(
                        request.form,
                        f"The first Strong identifier link must start with the earliest selected report in Template Library: {first_source['source_label']} (ingestion order {first_source['ingestion_order']}).",
                    )

        allow_creation = request.form.get("allow_object_creation") == "on"
        creation_authorized_by_source: dict[str, int] = {}
        for item in selected_identifiers:
            if item["strength"] == "STRONG" and item.get("source_can_create_object") and item.get("can_create_identity"):
                creation_authorized_by_source[item["source_id"]] = creation_authorized_by_source.get(item["source_id"], 0) + 1
        if allow_creation and max(creation_authorized_by_source.values(), default=0) < 2:
            return object_template_error(request.form, "Object creation requires at least two selected Strong identifiers that their report templates explicitly authorize for creation.")

        available_property_options = {
            (item["source_id"], item["field_key"]): item
            for item in context["object_property_options"]
        }
        prior_properties = {
            (str(item.get("source_id", "")), str(item.get("field_key", ""))): item
            for item in prior_definition.get("properties", ())
        }
        posted_property_sources = request.form.getlist("property_source_ids")
        posted_property_fields = request.form.getlist("property_field_keys")
        posted_canonical_keys = request.form.getlist("canonical_property_keys")
        if any((posted_property_sources, posted_property_fields, posted_canonical_keys)):
            if not (len(posted_property_sources) == len(posted_property_fields) == len(posted_canonical_keys)):
                return object_template_error(request.form, "Review the canonical property mappings and submit each source field with one property key.")
            canonical_keys_by_ref: dict[tuple[str, str], str] = {}
            for source_id, field_key, canonical_key in zip(
                posted_property_sources, posted_property_fields, posted_canonical_keys
            ):
                ref = (str(source_id), str(field_key))
                canonical_key = str(canonical_key).strip()
                if ref in canonical_keys_by_ref or (
                    ref not in available_property_options and ref not in prior_properties
                ):
                    return object_template_error(request.form, "A canonical property mapping refers to a duplicate or unknown source field.")
                if not canonical_key or len(canonical_key) > 120:
                    return object_template_error(request.form, "Canonical property keys must contain between 1 and 120 characters.")
                if canonical_key != ref[1] and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,119}", canonical_key):
                    return object_template_error(request.form, "A new canonical key must start with a letter and contain only letters, numbers, periods, underscores, or hyphens. Existing source field keys can be retained as-is.")
                canonical_keys_by_ref[ref] = canonical_key
        else:
            canonical_keys_by_ref = {
                ref: str(prop.get("canonical_property_key") or ref[1])
                for ref, prop in prior_properties.items()
            }
        property_options = available_property_options
        properties = []
        mapped_property_keys: set[tuple[str, str]] = set()
        for source_id in selected_sources:
            for key, option in property_options.items():
                if key[0] == source_id:
                    canonical_key = canonical_keys_by_ref.get(
                        key,
                        str(prior_properties.get(key, {}).get("canonical_property_key") or key[1]),
                    )
                    canonical_ref = (source_id, canonical_key)
                    if canonical_ref in mapped_property_keys:
                        return object_template_error(
                            request.form,
                            f"Source {source_id!r} maps more than one field to property {canonical_key!r}; select one field per property until a combination rule is configured.",
                        )
                    mapped_property_keys.add(canonical_ref)
                    properties.append({**option, "canonical_property_key": canonical_key})
            if source_id not in current_sources:
                for key, item in prior_properties.items():
                    if key[0] == source_id:
                        properties.append({
                            **item,
                            "canonical_property_key": str(item.get("canonical_property_key") or key[1]),
                        })
        display_property_keys = {
            str(prop.get("canonical_property_key") or prop.get("field_key", ""))
            for prop in properties
            if (str(prop.get("source_id", "")), str(prop.get("field_key", ""))) in selected_identity_map
            and selected_identity_map[(str(prop.get("source_id", "")), str(prop.get("field_key", "")))].get("strength") in {"STRONG", "SUPPORTING"}
        }
        title_property_key = str(request.form.get("title_property_key", "")).strip()
        context_property_keys = list(dict.fromkeys(
            str(value).strip() for value in request.form.getlist("context_property_keys") if str(value).strip()
        ))
        if title_property_key and title_property_key not in display_property_keys:
            return object_template_error(request.form, "Choose a primary display value from the selected Strong or Supporting identifiers.")
        if any(key not in display_property_keys for key in context_property_keys):
            return object_template_error(request.form, "Choose supporting display values from the selected Strong or Supporting identifiers.")
        if title_property_key in context_property_keys:
            context_property_keys.remove(title_property_key)
        # Template Library owns the live ingestion sequence. The Object
        # Template stores membership and source-version references, not a
        # second copy of order that could become stale after Library reorders.
        source_templates = [
            {key: value for key, value in source_refs[source_id].items() if key != "ingestion_order"}
            for source_id in selected_sources
        ]
        definition = {
            "object_name": object_name,
            "allow_object_creation": allow_creation,
            "source_templates": source_templates,
            "properties": properties,
            "presentation": {
                "title_property_key": title_property_key,
                "context_property_keys": context_property_keys,
            },
            "identifiers": selected_identifiers,
            "matches": matches,
        }
        saved = object_templates.save_draft(definition, current_actor())
        flash(f"{object_name} object template saved as draft v{saved['version_number']}.", "success")
        if request.headers.get("HX-Request") == "true":
            response = make_response("", 200)
            response.headers["HX-Redirect"] = url_for("ingestion_configuration.template_library")
            return response
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.post("/library/template-object/<version_id>/approve")
    @approver_required
    def approve_object_template(version_id: str):
        if object_template_catalog is None:
            return render_template(
                "admin/ingestion_template_library.html",
                **card_context(),
                error="The SharePoint root is not configured; this Object Template cannot be approved for the engine.",
            ), 400
        saved = object_templates.latest()
        if saved is None or saved["employee_template_version_id"] != version_id:
            return render_template(
                "admin/ingestion_template_library.html",
                **card_context(),
                error="Only the current saved Object Template draft can be approved here.",
            ), 409
        if saved.get("is_approved"):
            flash(f"Object Template v{saved['version_number']} is already approved for the engine.", "info")
            return redirect(url_for("ingestion_configuration.template_library"))
        try:
            object_template_catalog.approve_object_template(version_id, current_actor())
        except ValueError as exc:
            return render_template("admin/ingestion_template_library.html", **card_context(), error=str(exc)), 400
        flash(f"Object Template v{saved['version_number']} approved and available to the engine.", "success")
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.get("/library/<version_id>/identity-settings")
    @admin_required
    def identity_settings_page(version_id: str):
        return redirect(url_for("ingestion_configuration.template_settings_page", version_id=version_id))

    @blueprint.get("/library/<version_id>/identity-field-row")
    @admin_required
    def identity_field_row(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        current_rows = request.args.getlist("identity_row_indices")
        requested_limit = _positive_int(
            request.args.get("identity_matching_limit", ""),
            default=draft.identity_governance.max_matching_fields,
        )
        if len(current_rows) >= requested_limit:
            return "", 204
        return render_template(
            "admin/_ingestion_identity_field_row.html",
            row_index=max(0, _positive_int(request.args.get("index", "0"), default=0)),
            available_fields=tuple(field for field in draft.fields if field.include),
            selected_key="",
            selected_strength="STRONG",
            selected_create=False,
        )

    def save_template_settings_response(version_id: str):
        saved = templates.get(version_id)
        if saved is None:
            return "Template version not found.", 404
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        configured = _identity_settings_from_form(draft, request.form) if "identity_role" in request.form else draft
        try:
            business_rule_source_system = str(request.form.get(
                "business_rule_source_system", configured.business_rule_source_system,
            )).strip().upper()
            allowed_rule_sources = {item["key"] for item in rule_source_systems()}
            if business_rule_source_system and business_rule_source_system not in allowed_rule_sources:
                raise ValueError("Choose an active Business Rules source or leave the source mapping blank.")
            folder = str(request.form.get("folder_path", draft.watched_subfolder)).strip()
            new_folder = str(request.form.get("create_folder_path", "")).strip()
            if not folder and not new_folder:
                raise ValueError("Choose an existing watch folder or enter a folder to create before validating this template.")
            watched_subfolder = (
                safe_sharepoint_subfolder(new_folder, create=False, allow_missing=True)
                if new_folder else safe_sharepoint_subfolder(folder, create=False)
            )

            mode = str(request.form.get("timezone_mode", draft.date_time_settings.timezone_mode)).strip().upper()
            if mode not in {"RULE_CALENDAR", "CUSTOM"}:
                raise ValueError("Choose a valid time-zone source.")
            calendar = active_rule_calendar()
            source_timezone = str(request.form.get("source_timezone", draft.date_time_settings.source_timezone)).strip()
            target_timezone = str(request.form.get("target_timezone", draft.date_time_settings.target_timezone)).strip()
            if mode == "RULE_CALENDAR" and calendar["available"]:
                source_timezone = source_timezone or calendar["timezone"]
                target_timezone = target_timezone or calendar["timezone"]
            for timezone_name in (source_timezone, target_timezone):
                if timezone_name:
                    ZoneInfo(timezone_name)
                elif mode == "CUSTOM":
                    raise ValueError("Choose both the report time zone and the time zone for date/time values.")
            valid_temporal_keys = {
                field.field_key for field in configured.fields
                if field.include and field.data_type.casefold() in {"date", "datetime", "timestamp"}
            }
            timezone_field_keys = (
                tuple(key for key in request.form.getlist("timezone_field_keys") if key in valid_temporal_keys)
                if request.form.get("combined_settings") == "1" or "timezone_field_keys" in request.form
                else configured.date_time_settings.field_keys
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

            skip_rules = configured.skip_rules
            if "skip_field_key" in request.form:
                skip_field_key = str(request.form.get("skip_field_key", "")).strip()
                skip_rules = ()
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
                configured,
                business_rule_source_system=business_rule_source_system,
                watched_subfolder=watched_subfolder,
                date_time_settings=date_time_settings,
                skip_rules=skip_rules,
            )
            validation_errors = DraftConfigurationService.validate(configured)
            if validation_errors:
                raise ValueError(" ".join(validation_errors))
            if new_folder:
                safe_sharepoint_subfolder(new_folder, create=True)
            templates.save_draft(
                configured.to_dict(), current_actor(),
                version_id if saved["status"] == "DRAFT" else None,
                mark_validated=True,
            )
        except (ValueError, OSError, ZoneInfoNotFoundError) as exc:
            return render_template_settings_page(
                version_id, error=str(exc), form_values=request.form, configured=configured,
            ), 400
        flash("Template settings validated and saved. This version is ready for approval.", "success")
        return redirect(url_for("ingestion_configuration.template_library"))

    @blueprint.post("/library/<version_id>/identity-settings")
    @admin_required
    def save_identity_settings(version_id: str):
        return save_template_settings_response(version_id)

    @blueprint.post("/library/<version_id>/behavior-settings")
    @admin_required
    def save_behavior_settings(version_id: str):
        return save_template_settings_response(version_id)

    @blueprint.get("/library/<version_id>/settings")
    @admin_required
    def template_settings_page(version_id: str):
        return render_template_settings_page(version_id)

    @blueprint.post("/library/<version_id>/settings")
    @admin_required
    def save_template_settings(version_id: str):
        return save_template_settings_response(version_id)

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
    def behavior_settings_page(version_id: str):
        return redirect(url_for("ingestion_configuration.template_settings_page", version_id=version_id))

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
        if not templates.is_validated(version_id):
            return render_template(
                "admin/ingestion_template_library.html",
                **card_context(),
                error="Validate and save all template settings before approving this version.",
            ), 400
        draft = DraftSourceDefinition.from_dict(saved["definition"])
        try:
            safe_sharepoint_subfolder(draft.watched_subfolder, create=False)
        except ValueError as exc:
            return render_template("admin/ingestion_template_library.html", **card_context(), error=str(exc)), 400
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
        # DEPRECATED compatibility: the current schema editor has no canonical
        # mapping controls. Continue accepting old form posts without changing
        # the versioned field-key contract.
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
        business_rule_source_system=str(form.get("business_rule_source_system", "")).strip().upper(),
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
        recognition_settings=replace(
            draft.recognition_settings,
            extension=".csv" if inspection.get("format") == "CSV" else ".xlsx",
            sheet_name=str(inspection.get("selected_sheet", "")),
            required_headers=tuple(
                str(header)
                for header in draft.recognition_settings.required_headers
                if str(header).strip().casefold() in {
                    field.source_name.strip().casefold() for field in fields if field.include
                }
            ),
        ),
        # The configuration laboratory describes source schema only. Canonical
        # or shared object mappings are intentionally deferred to the future Object Engine.
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
    included_source_names = {
        field.source_name.strip().casefold() for field in fields if field.include
    }
    if form.get("recognition_headers_present") == "1":
        recognition_headers = tuple(
            field.source_name for index, field in enumerate(fields)
            if field.include and form.get(f"recognition_header_{index}") == "on"
        )
    else:
        recognition_headers = tuple(
            header for header in draft.recognition_settings.required_headers
            if str(header).strip().casefold() in included_source_names
        )
    return replace(
        _draft_with_source_basics(draft, form, draft.reader_settings.filename_pattern or draft.display_name),
        business_rule_source_system=str(form.get("business_rule_source_system", draft.business_rule_source_system)).strip().upper(),
        fields=fields,
        identity_governance=identity_governance,
        recognition_settings=replace(
            draft.recognition_settings,
            required_headers=recognition_headers,
        ),
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
    try:
        max_matching_fields = int(form.get("identity_matching_limit", draft.identity_governance.max_matching_fields))
    except (TypeError, ValueError):
        max_matching_fields = 0
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
            max_matching_fields=max_matching_fields,
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
        max_matching_fields=draft.identity_governance.max_matching_fields,
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
        business_rule_source_system=draft.business_rule_source_system,
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
    included_source_names = {
        field.source_name.strip().casefold() for field in fields if field.include
    }
    return DraftSourceDefinition(
        source_id=draft.source_id,
        display_name=draft.display_name,
        description=draft.description,
        business_rule_source_system=draft.business_rule_source_system,
        reader_settings=draft.reader_settings,
        recognition_settings=replace(
            draft.recognition_settings,
            required_headers=tuple(
                header for header in draft.recognition_settings.required_headers
                if str(header).strip().casefold() in included_source_names
            ),
        ),
        fields=fields,
        identity_governance=DraftIdentityGovernance(
            role=draft.identity_governance.role,
            can_create_employee=draft.identity_governance.can_create_employee,
            identifiers=tuple(
                identifier
                for identifier in draft.identity_governance.identifiers
                if removed_field_key is None or identifier.field_key != removed_field_key
            ),
            max_matching_fields=draft.identity_governance.max_matching_fields,
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
