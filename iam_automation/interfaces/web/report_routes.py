"""
File: iam_automation/interfaces/web/report_routes.py
Purpose: Defines Flask routes for the report routes area.
Responsibilities: Exposes or coordinates: create_report_blueprint.
Dependencies: flask, application
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
import csv
import io
from functools import wraps
from pathlib import Path

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for, send_file

from ...application.employee_service import CANONICAL_DUPLICATE_REPORT_COLUMNS, EmployeeService
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
            return render_template("reports/duplicates.html", duplicate_summary=None, duplicate_mode="")
        return render_template("reports/index.html", report=service.snapshot())

    @blueprint.get("/vendors")
    @authenticated
    def vendor_report():
        return render_template("reports/vendors.html", report=service.snapshot())

    @blueprint.get("/duplicates")
    @authenticated
    def duplicate_report():
        duplicate_mode = request.args.get("type", "").strip().lower()
        duplicate_summary = None
        canonical_rows = None
        if duplicate_mode == "canonical":
            canonical_rows = employee_service.canonical_duplicate_report_rows()
        if duplicate_mode in {"source_identifier", "name_email", "unresolved"}:
            duplicate_summary = employee_service.source_duplicate_summary()
            if duplicate_mode == "source_identifier":
                duplicate_summary["groups"] = [group for group in duplicate_summary["groups"] if group["signal"] != "Name + email"]
            elif duplicate_mode == "name_email":
                duplicate_summary["groups"] = [group for group in duplicate_summary["groups"] if group["signal"] == "Name + email"]
            elif duplicate_mode == "unresolved":
                duplicate_summary["groups"] = [group for group in duplicate_summary["groups"] if group["classification"] == "REVIEW_DUPLICATE"]
            duplicate_summary["group_count"] = len(duplicate_summary["groups"])
        return render_template("reports/duplicates.html", duplicate_summary=duplicate_summary, canonical_rows=canonical_rows, duplicate_mode=duplicate_mode)

    @blueprint.get("/duplicates/export")
    @authenticated
    def duplicate_report_export():
        if request.args.get("type", "").strip().lower() != "canonical":
            return Response("Only canonical duplicate export is available.", status=400, mimetype="text/plain")
        rows = employee_service.canonical_duplicate_report_rows()
        columns = list(CANONICAL_DUPLICATE_REPORT_COLUMNS)
        export_format = request.args.get("format", "csv").strip().lower()
        if export_format == "xlsx":
            from openpyxl import Workbook
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Canonical duplicates"
            sheet.append(columns)
            for row in rows:
                sheet.append([row[column] for column in columns])
            output = io.BytesIO()
            workbook.save(output)
            output.seek(0)
            return send_file(output, as_attachment=True, download_name="canonical-duplicate-report.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row[column] for column in columns} for row in rows)
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=canonical-duplicate-report.csv"})

    @blueprint.get("/new-hires")
    @authenticated
    def new_hire_report():
        return render_template("reports/new_hires.html", new_hires=service.new_hire_readiness())

    @blueprint.get("/terminations")
    @authenticated
    def termination_report():
        return render_template(
            "reports/terminations.html",
            report=service.termination_report(
                start_date=request.args.get("start"),
                end_date=request.args.get("end"),
            ),
        )

    @blueprint.route("/studio", methods=["GET", "POST"])
    @authenticated
    def report_studio():
        form = request.form if request.method == "POST" else request.args
        username = str(session.get("iam_user", ""))
        saved_template = template_service.get_for_user(request.args.get("template_id", ""), username) if template_service and request.method == "GET" else None
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
            templates=template_service.list_for_user(username) if template_service else [],
            template_folders=template_service.list_folders(username) if template_service else [],
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
            username = str(session.get("iam_user", ""))
            folder_id = str(payload.get("folder_id", ""))
            if folder_id and template_service.get_folder_for_user(folder_id, username) is None:
                raise ValueError("The selected folder is not available to this user.")
            template = template_service.save(
                name=name,
                definition=definition,
                created_by=username,
                folder_id=folder_id,
                shared=str(payload.get("shared", "")).lower() in {"1", "true", "yes", "on"} if not isinstance(payload.get("shared"), bool) else payload.get("shared"),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"template_id": template.template_id, "name": template.name, "folder_id": template.folder_id, "shared": template.shared})

    @blueprint.post("/studio/folders")
    @authenticated
    def save_report_template_folder():
        if template_service is None:
            return jsonify({"error": "SharePoint storage is not configured."}), 503
        payload = request.get_json(silent=True) or request.form
        try:
            shared = payload.get("shared", False)
            if not isinstance(shared, bool):
                shared = str(shared).lower() in {"1", "true", "yes", "on"}
            folder = template_service.save_folder(name=str(payload.get("name", "")), created_by=str(session.get("iam_user", "")), shared=shared)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"folder_id": folder.folder_id, "name": folder.name, "shared": folder.shared})

    return blueprint
#endfile
