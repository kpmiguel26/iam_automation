from __future__ import annotations

import json
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from ...application.employee_service import EmployeeService
from ...application.report_service import ReportService, ReportStudioResult
from ...application.report_template_service import ReportTemplateService


def create_report_blueprint(database_path: Path, sharepoint_root: Path | None = None) -> Blueprint:
    blueprint = Blueprint("reports", __name__, url_prefix="/reports")
    service = ReportService(database_path)
    employee_service = EmployeeService(database_path)
    template_service = ReportTemplateService(sharepoint_root) if sharepoint_root else None

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @blueprint.get("")
    @authenticated
    def reports_home():
        if request.args.get("duplicates", "") == "1":
            return render_template("reports/duplicates.html", duplicate_summary=employee_service.source_duplicate_summary())
        return render_template("reports/index.html", report=service.snapshot())

    @blueprint.get("/vendors")
    @authenticated
    def vendor_report():
        return render_template("reports/vendors.html", report=service.snapshot())

    @blueprint.get("/duplicates")
    @authenticated
    def duplicate_report():
        return render_template("reports/duplicates.html", duplicate_summary=employee_service.source_duplicate_summary())

    @blueprint.get("/new-hires")
    @authenticated
    def new_hire_report():
        return render_template("reports/new_hires.html", new_hires=service.new_hire_readiness())

    @blueprint.route("/studio", methods=["GET", "POST"])
    @authenticated
    def report_studio():
        form = request.form if request.method == "POST" else request.args
        saved_template = template_service.get(request.args.get("template_id", "")) if template_service and request.method == "GET" else None
        definition = saved_template.definition if saved_template else {}
        source = str(definition.get("sources", [form.get("source", "ALL")])[0] if definition.get("sources") else form.get("source", "ALL"))
        selected_columns = list(definition.get("columns", [])) if saved_template else (form.getlist("columns") if hasattr(form, "getlist") else [])
        submitted_filters = definition.get("filters", []) if saved_template else []
        if not saved_template:
            try:
                submitted_filters = json.loads(form.get("filters_json", "[]"))
                if not isinstance(submitted_filters, list):
                    submitted_filters = []
            except (TypeError, json.JSONDecodeError):
                submitted_filters = []
        filter_field = str(definition.get("filters", [{}])[0].get("field", "") if saved_template and definition.get("filters") else form.get("filter_field", ""))
        filter_operator = str(definition.get("filters", [{}])[0].get("operator", "equals") if saved_template and definition.get("filters") else form.get("filter_operator", "equals"))
        filter_value = definition.get("filters", [{}])[0].get("value", "") if saved_template and definition.get("filters") else form.get("filter_value", "")
        sort_field = str(definition.get("sort", [{}])[0].get("field", "") if saved_template and definition.get("sort") else form.get("sort_field", ""))
        sort_direction = str(definition.get("sort", [{}])[0].get("direction", "desc") if saved_template and definition.get("sort") else form.get("sort_direction", "desc"))
        limit = definition.get("limit", "all") if saved_template else form.get("limit", "all")
        fields = service.field_catalog(source)
        should_preview = request.method == "POST" or saved_template is not None
        if not should_preview:
            preview = ReportStudioResult(
                fields=(),
                rows=(),
                total_rows=0,
                definition={"sources": [source], "columns": [], "filters": [], "sort": [], "limit": None},
                filter_options={},
            )
        else:
            preview = service.studio_preview(
                source=source,
                columns=selected_columns,
                filter_field=filter_field,
                filter_operator=filter_operator,
                filter_value=filter_value,
                filters=submitted_filters,
                sort_field=sort_field,
                sort_direction=sort_direction,
                limit=limit,
            )
        field_groups = service.field_groups(source, fields=fields)
        return render_template(
            "reports/studio.html",
            sources=service.source_catalog(),
            fields=fields,
            field_groups=field_groups,
            preview=preview,
            selected_source=source,
            selected_columns=set(selected_columns),
            filter_field=filter_field,
            filter_operator=filter_operator,
            filter_value=filter_value,
            sort_field=sort_field,
            sort_direction=sort_direction,
            limit=limit,
            filters_json=json.dumps(submitted_filters),
            templates=template_service.list() if template_service else [],
            active_template_id=saved_template.template_id if saved_template else "",
        )

    @blueprint.get("/studio/filter-options")
    @authenticated
    def report_studio_filter_options():
        source = request.args.get("source", "ALL")
        fields = [field for field in request.args.getlist("field") if field]
        result = service.studio_preview(source=source, columns=fields, limit=1)
        return jsonify({key: list(values) for key, values in result.filter_options.items() if key in fields})

    @blueprint.post("/studio/templates")
    @authenticated
    def save_report_template():
        if template_service is None:
            return jsonify({"error": "SharePoint storage is not configured."}), 503
        payload = request.get_json(silent=True) or request.form
        name = str(payload.get("name", ""))
        try:
            definition = payload.get("definition", {})
            if isinstance(definition, str):
                definition = json.loads(definition)
            if not isinstance(definition, dict):
                raise ValueError("Invalid report definition.")
            template = template_service.save(name=name, definition=definition, created_by=str(session.get("iam_user", "")))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"template_id": template.template_id, "name": template.name})

    return blueprint
