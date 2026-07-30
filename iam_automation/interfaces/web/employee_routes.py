from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.audit_service import record_audit
from ...application.employee_service import EmployeeService
from ...application.request_service import OPERATION_OPTIONS, RequestService
from ...application.shared_request_service import SharedRequestService
from ...identity import CurrentUser


def create_employee_blueprint(database_path: Path, *, sharepoint_root: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("employees", __name__, url_prefix="/employees")
    service = EmployeeService(database_path)
    requests = SharedRequestService(sharepoint_root) if sharepoint_root else RequestService(database_path)

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return "Application login required.", 401
            return view(*args, **kwargs)
        return wrapped

    @blueprint.get("")
    @authenticated
    def employee_directory():
        search = request.args.get("q", "")
        status = request.args.get("status", "ALL")
        vendor = request.args.get("vendor", "ALL")
        source = request.args.get("source", "ALL")
        engagement = request.args.get("engagement", "")
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        requested_page = page
        statuses, vendors, sources = service.filter_values()
        workers, total_workers = service.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, page=page, per_page=25)
        page_count = max(1, (total_workers + 24) // 25)
        page = min(page, page_count)
        if page != requested_page:
            workers, total_workers = service.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, page=page, per_page=25)
        return render_template("employees/list.html", workers=workers, statuses=statuses, vendors=vendors, sources=sources, filters={"q": search, "status": status, "vendor": vendor, "source": source, "engagement": engagement}, page=page, page_count=page_count, total_workers=total_workers)

    @blueprint.get("/<worker_id>")
    @authenticated
    def employee_detail(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/detail.html", operation_options=OPERATION_OPTIONS, message=request.args.get("notice"), error=request.args.get("error"), **detail)

    @blueprint.post("/<worker_id>/request")
    @authenticated
    def request_employee_change(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        try:
            actor = str(session["iam_user"])
            worker = detail["worker"]
            engagement = detail["engagements"][0] if detail["engagements"] else None
            current_values = {
                "first_name": worker.first_name or "",
                "last_name": worker.last_name or "",
                "email": worker.canonical_email or "",
                "status": worker.status or "",
                "job_title": engagement.job_title if engagement else "",
                "lob": engagement.lob if engagement else "",
                "vendor_name": engagement.vendor_name if engagement else "",
                "program": engagement.program if engagement else "",
                "project": engagement.project if engagement else "",
                "country": engagement.country if engagement else "",
                "site_location": engagement.site_location if engagement else "",
                "supervisor_name": engagement.supervisor_name if engagement else "",
                "onboarding_date": engagement.onboarding_date if engagement else "",
                "production_start_date": engagement.production_start_date if engagement else "",
                "engagement_status": engagement.status if engagement else "",
                "npn": engagement.npn if engagement else "",
                "license_state": engagement.license_state if engagement else "",
                "license_number": engagement.license_number if engagement else "",
                "taxonomy_code": engagement.taxonomy_code if engagement else "",
                "key_billable_function": engagement.key_billable_function if engagement else "",
            }
            submitted_values = {key: request.form.get(key, "").strip() for key in current_values}
            payload = {
                key: value
                for key, value in submitted_values.items()
                if value != current_values[key]
            }
            identifier_updates = {
                identifier.identifier_id: request.form.get(f"identifier_{identifier.identifier_id}", "").strip()
                for identifier in detail["identifiers"]
                if request.form.get(f"identifier_{identifier.identifier_id}", "").strip() != identifier.identifier_value
            }
            lineage_updates = {
                lineage.lineage_id: request.form.get(f"lineage_{lineage.lineage_id}", "").strip()
                for lineage in detail["lineage"]
                if request.form.get(f"lineage_{lineage.lineage_id}", "").strip() != lineage.normalized_value
            }
            if identifier_updates:
                payload["identifier_updates"] = identifier_updates
            if lineage_updates:
                payload["lineage_updates"] = lineage_updates
            if not payload:
                raise ValueError("No changes were entered.")
            operation_type = "DEACTIVATE_EMPLOYEE" if payload.get("status") in {"INACTIVE", "TERMINATED"} else "UPDATE_EMPLOYEE"
            item = requests.create(
                CurrentUser(actor, "local-web", tuple(session.get("iam_roles", ()))),
                operation_type,
                worker_id,
                payload,
                request.form.get("reason", ""),
            )
            record_audit(audit_path, actor, "EMPLOYEE_CHANGE_REQUEST_CREATED", "worker", worker_id, new_values={"request_id": item.request_id, "operation_type": item.operation_type})
            return redirect(url_for("employees.employee_detail", worker_id=worker_id, notice=f"Request {item.request_id[:8]} submitted for reviewer approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.employee_detail", worker_id=worker_id, error=str(exc), notice_type="danger"))

    return blueprint
