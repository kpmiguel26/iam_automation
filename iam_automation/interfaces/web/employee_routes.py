"""
File: iam_automation/interfaces/web/employee_routes.py
Purpose: Defines Flask routes for the employee routes area.
Responsibilities: Exposes or coordinates: create_employee_blueprint.
Dependencies: flask, application, identity
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.audit_service import record_audit
from ...application.employee_service import EmployeeService
from ...application.notification_service import NotificationService
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
        review = request.args.get("review", "")
        show_all = request.args.get("all", "") == "1"
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1
        page = requested_page
        statuses, vendors, sources = service.filter_values()
        has_query = bool(show_all or search.strip() or engagement.strip() or review or status != "ALL" or vendor != "ALL" or source != "ALL")
        workers, total_workers = (service.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, review=review, page=page, per_page=25) if has_query else ([], 0))
        page_count = max(1, (total_workers + 24) // 25)
        page = min(page, page_count)
        if has_query and page != requested_page:
            workers, total_workers = service.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, review=review, page=page, per_page=25)
        rehire_alerts = service.rehire_alerts()
        NotificationService(database_path).notify_rehire_alerts(rehire_alerts)
        return render_template("employees/list.html", workers=workers, statuses=statuses, vendors=vendors, sources=sources, filters={"q": search, "status": status, "vendor": vendor, "source": source, "engagement": engagement, "review": review, "all": show_all}, page=page, page_count=page_count, total_workers=total_workers, has_query=has_query, pending_source_updates=service.pending_source_update_count(), rehire_alert_count=len(rehire_alerts))

    @blueprint.get("/source-updates")
    @authenticated
    def source_updates_overview():
        source_system = request.args.get("source", "").strip()
        source_file = request.args.get("file", "").strip()
        mode = request.args.get("mode", "").strip().lower()
        person_query = request.args.get("person", "").strip()
        all_people = request.args.get("all_people", "") == "1"
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1
        page = requested_page
        sources = service.list_source_systems()
        files = service.list_source_files(source_system) if source_system else []
        file_summary = service.get_source_file_summary(source_system, source_file) if source_system and source_file else None
        records, total_records = service.list_source_records(source_system, source_file, page=page, per_page=50) if file_summary else ([], 0)
        page_count = max(1, (total_records + 49) // 50)
        page = min(page, page_count)
        if file_summary and page != requested_page:
            records, total_records = service.list_source_records(source_system, source_file, page=page, per_page=50)
        duplicate_summary = service.source_duplicate_summary(source_file=source_file) if mode == "duplicates" else None
        people = service.list_source_people() if all_people else service.search_source_people(person_query) if person_query else []
        rehire_alerts = service.rehire_alerts(source_file if source_system == "ROSTER_LOCK" else "")
        NotificationService(database_path).notify_rehire_alerts(rehire_alerts)
        return render_template(
            "employees/source_updates_overview.html",
            sources=sources,
            files=files,
            records=records,
            total_records=total_records,
            page=page,
            page_count=page_count,
            source_system=source_system,
            source_file=source_file,
            file_summary=file_summary,
            mode=mode,
            duplicate_summary=duplicate_summary,
            person_query=person_query,
            people=people,
            all_people=all_people,
            rehire_alerts=rehire_alerts,
        )

    @blueprint.post("/source-updates/create-all")
    @authenticated
    def create_all_source_candidates():
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice="Only an administrator can run bulk creation.", notice_type="danger"))
        try:
            result = service.create_all_source_candidates(current_user.username)
            record_audit(audit_path, current_user.username, "ALL_SOURCE_CANDIDATES_APPLIED", "source_updates", "bulk", new_values={"result": result})
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice=f"Processed {result['dossiers']} record(s): {result['created']} employee(s) created, {result['reused']} reused, {result['skipped']} skipped, and {result['failed']} failed.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/rehire-alert/<record_id>/resolve")
    @authenticated
    def resolve_rehire_alert(record_id: str):
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_updates_overview", error="Only an administrator can archive a rehire alert.", notice_type="danger"))
        try:
            reason = request.form.get("reason", "").strip()
            result = service.resolve_rehire_alert(record_id, current_user.username, reason)
            record_audit(audit_path, current_user.username, "REHIRE_ALERT_ARCHIVED", "ingestion_record", record_id, new_values={"result": result, "reason": reason})
            return redirect(url_for("employees.source_updates_overview", notice="Rehire alert archived. Source evidence and employee status were not changed.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates_overview", error=str(exc), notice_type="danger"))

    @blueprint.route("/source-updates/duplicate/<record_id>", methods=["GET", "POST"])
    @authenticated
    def duplicate_review(record_id: str):
        review = service.duplicate_review(record_id)
        if review is None:
            return render_template("errors/404.html"), 404
        message = error = None
        if request.method == "POST":
            if request.form.get("action") == "use_latest":
                try:
                    result = service.resolve_source_duplicate(record_id, str(session["iam_user"]))
                    return redirect(url_for("employees.source_updates_overview", notice=f"Canonical employee created/updated from the latest {result['source_system']} observation. {len(result['superseded_record_ids'])} older observation(s) were preserved as history.", notice_type="success"))
                except (OSError, ValueError, PermissionError) as exc:
                    error = str(exc)
            elif not review.get("worker_id"):
                error = "This group does not yet have a single canonical employee to apply the selected values to."
            else:
                choices = {key.removeprefix("field_"): value for key, value in request.form.items() if key.startswith("field_") and value}
                try:
                    grouped: dict[str, list[str]] = {}
                    for field, source_record_id in choices.items():
                        grouped.setdefault(source_record_id, []).append(field)
                    results = [service.apply_selected_source_updates(review["worker_id"], [source_record_id], fields, str(session["iam_user"])) for source_record_id, fields in grouped.items()]
                    message = f"Applied {sum(int(result['processed']) for result in results)} record(s) locally and updated the history."
                except (OSError, ValueError, PermissionError) as exc:
                    error = str(exc)
        return render_template("employees/duplicate_review.html", review=review, message=message, error=error)

    @blueprint.get("/source-updates/candidate/<record_id>")
    @authenticated
    def source_candidate(record_id: str):
        preview = service.source_candidate_preview(record_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        return render_template("employees/source_candidate.html", preview=preview, can_apply=current_user.can_decide_requests, message=request.args.get("notice"), error=request.args.get("error"))

    def _request_source_change(*, operation_type: str, entity_id: str, payload: dict[str, object], reason: str, actor: str) -> str:
        current_user = CurrentUser(actor, "local-web", tuple(session.get("iam_roles", ())))
        item = requests.create(current_user, operation_type, entity_id, payload, reason)
        request_id = item.request_id
        NotificationService(database_path).notify_request_reviewers(request_id, operation_type, actor, record_count=len(payload.get("record_ids", [])))
        record_audit(audit_path, actor, "SOURCE_CHANGE_REQUEST_CREATED", "change_request", request_id, new_values={"operation_type": operation_type, "record_count": len(payload.get("record_ids", []))})
        return request_id

    @blueprint.get("/<worker_id>")
    @authenticated
    def employee_detail(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/detail.html", operation_options=OPERATION_OPTIONS, message=request.args.get("notice"), error=request.args.get("error"), **detail)

    @blueprint.get("/<worker_id>/edit")
    @authenticated
    def employee_edit(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/edit.html", operation_options=OPERATION_OPTIONS, message=request.args.get("notice"), error=request.args.get("error"), **detail)

    @blueprint.get("/<worker_id>/history")
    @authenticated
    def employee_history(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/history.html", **detail)

    @blueprint.get("/<worker_id>/source-updates")
    @authenticated
    def source_updates(worker_id: str):
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        rehire_alerts = [item for item in service.rehire_alerts() if str(item.get("worker_id", "")) == worker_id]
        NotificationService(database_path).notify_rehire_alerts(rehire_alerts)
        return render_template("employees/source_updates.html", preview=preview, rehire_alerts=rehire_alerts, can_apply=current_user.can_decide_requests, message=request.args.get("notice"), error=request.args.get("error"))

    @blueprint.post("/source-updates/<worker_id>/apply")
    @authenticated
    def apply_source_updates(worker_id: str):
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="Only an administrator can apply source changes directly.", notice_type="danger"))
        if service.rehire_alerts_for_worker(worker_id):
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="Critical rehire alert: this employee is still within the 30-business-day rehire hold and cannot be applied.", notice_type="danger"))
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        record_ids = sorted({str(update["record_id"]) for update in preview["updates"]})
        if not record_ids:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="No pending source changes are available.", notice_type="warning"))
        try:
            result = service.apply_selected_source_updates(worker_id, record_ids, request.form.getlist("apply_fields"), current_user.username)
            record_audit(audit_path, current_user.username, "EMPLOYEE_SOURCE_CHANGE_APPLIED", "worker", worker_id, new_values={"record_ids": record_ids, "result": result})
            return redirect(url_for("employees.source_updates", worker_id=worker_id, notice=f"Applied locally: {result.get('processed', 0)} source record(s). History updated. Publish SQLite separately to share it.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/<worker_id>/request")
    @authenticated
    def request_source_updates(worker_id: str):
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        record_ids = sorted({str(update["record_id"]) for update in preview["updates"]})
        if not record_ids:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="No pending source changes are available.", notice_type="warning"))
        try:
            actor = str(session["iam_user"])
            request_id = _request_source_change(
                operation_type="UPDATE_EMPLOYEE",
                entity_id=worker_id,
                payload={"source_delta": True, "worker_id": worker_id, "record_ids": record_ids, "source_updates": preview["updates"], "fields": preview.get("fields", []), "apply_fields": request.form.getlist("apply_fields")},
                reason=request.form.get("reason", "Source update review"),
                actor=actor,
            )
            return redirect(url_for("employees.source_updates", worker_id=worker_id, notice=f"Request {request_id[:8]} submitted for administrator approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/candidate/<record_id>/apply")
    @authenticated
    def apply_source_candidate(record_id: str):
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error="Only an administrator can apply source changes directly.", notice_type="danger"))
        try:
            preview = service.source_candidate_preview(record_id)
            if preview is None:
                return render_template("errors/404.html"), 404
            record_ids = [str(item["record_id"]) for item in preview.get("records", [])]
            preparation = service.prepare_source_candidate(record_ids or [record_id], current_user.username)
            result = service.apply_approved_import_records(record_ids or [record_id], current_user.username)
            record_audit(audit_path, current_user.username, "NEW_EMPLOYEE_SOURCE_APPLIED", "ingestion_record", record_id, new_values={"result": result})
            return redirect(url_for("employees.source_candidate", record_id=record_id, notice=f"Applied {result.get('processed', 0)} source record(s) to one canonical employee. {'Created' if preparation['created'] else 'Reused'} worker {preparation['worker_id'][:8]}.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/candidate/<record_id>/request")
    @authenticated
    def request_source_candidate(record_id: str):
        preview = service.source_candidate_preview(record_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        try:
            actor = str(session["iam_user"])
            operation_type = "IMPORT_RSR_SUPPLIER_DETAILS" if preview["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS" else "IMPORT_ACCESSNOW" if preview["source_system"] == "ACCESSNOW" else "IMPORT_ROSTER_LOCK"
            evidence = list(preview.get("records", []))
            record_ids = [str(item["record_id"]) for item in evidence] or [record_id]
            request_id = _request_source_change(operation_type=operation_type, entity_id=str(preview["batch_id"]), payload={"record_ids": record_ids, "record_previews": evidence or [preview]}, reason=request.form.get("reason", "New source employee review"), actor=actor)
            return redirect(url_for("employees.source_candidate", record_id=record_id, notice=f"Request {request_id[:8]} submitted for administrator approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error=str(exc), notice_type="danger"))

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
