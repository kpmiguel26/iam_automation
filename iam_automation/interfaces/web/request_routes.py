from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, session

from ...application.request_service import OPERATION_OPTIONS, RequestService
from ...application.shared_request_service import SharedRequestService
from ...application.audit_service import record_audit
from ...application.employee_service import EmployeeService
from ...application.notification_service import NotificationService
from ...application.user_service import UserService
from ...identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_REVIEWER, ROLE_SUPER_OPERATOR, normalize_role


def _current_user() -> CurrentUser:
    return CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))


def create_request_blueprint(database_path: Path, *, sharepoint_root: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("requests", __name__)
    service = SharedRequestService(sharepoint_root) if sharepoint_root else RequestService(database_path)
    users = UserService(database_path)
    notifications = NotificationService(database_path)
    employees = EmployeeService(database_path)

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return "Application login required.", 401
            return view(*args, **kwargs)
        return wrapped

    def reviewer_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not _current_user().can_review_requests:
                return "Reviewer or administrator access required.", 403
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Application Admin role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def reviewer_accounts():
        eligible = {ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}
        return [
            user for user in users.list_users()
            if user.active and {normalize_role(role) for role in user.roles} & eligible
        ]

    def queue_context():
        """Build the approval view consistently after every queue action."""
        queued = service.list_requests(queue=True)
        recent_decisions = [
            item for item in service.list_requests()
            if item.operation_type in {"IMPORT_ROSTER_LOCK", "IMPORT_RSR_SUPPLIER_DETAILS"}
            and item.status in {"APPROVED", "REJECTED"}
        ][:10]
        return {"requests": queued, "recent_decisions": recent_decisions, "reviewers": reviewer_accounts()}

    @blueprint.get("/requests")
    @authenticated
    def request_list():
        return render_template("requests/list.html", requests=service.list_requests(creator=str(session["iam_user"])), operation_options=OPERATION_OPTIONS, message=None, error=None)

    @blueprint.route("/requests/new", methods=["GET", "POST"])
    @authenticated
    def new_request():
        error = None
        if request.method == "POST":
            try:
                payload = {key: value.strip() for key, value in {"first_name": request.form.get("first_name", ""), "last_name": request.form.get("last_name", ""), "job_title": request.form.get("job_title", ""), "lob": request.form.get("lob", "")}.items() if value.strip()}
                created = service.create(_current_user(), request.form.get("operation_type", ""), request.form.get("entity_id", ""), payload, request.form.get("reason", ""))
                notifications.notify_request_reviewers(
                    created.request_id,
                    created.operation_type,
                    created.created_by,
                    record_count=1,
                )
                record_audit(audit_path, str(session["iam_user"]), "REQUEST_CREATED", "change_request", request.form.get("entity_id", ""), new_values={"operation_type": request.form.get("operation_type", "")})
                return render_template("requests/list.html", requests=service.list_requests(creator=str(session["iam_user"])), operation_options=OPERATION_OPTIONS, message="Request submitted and shared connector JSON created in SharePoint.", error=None)
            except (OSError, ValueError, PermissionError) as exc:
                error = str(exc)
        return render_template("requests/new.html", operation_options=OPERATION_OPTIONS, error=error)

    @blueprint.get("/admin/approvals")
    @authenticated
    @reviewer_required
    def approval_queue():
        service.escalate_overdue((str(session["iam_user"]),))
        return render_template("requests/approval_queue.html", **queue_context(), message=None, error=None)

    @blueprint.post("/admin/approvals/<request_id>/assign")
    @authenticated
    @admin_required
    def assign_request(request_id: str):
        try:
            item = service.assign(request_id, request.form.get("reviewer", ""), str(session["iam_user"]), request.form.get("reason", ""))
            record_audit(audit_path, str(session["iam_user"]), "REQUEST_ASSIGNED", "change_request", request_id, new_values={"reviewer": item.assigned_to})
            return render_template("requests/approval_queue.html", **queue_context(), message="Reviewer assigned.", error=None)
        except (ValueError, PermissionError) as exc:
            return render_template("requests/approval_queue.html", **queue_context(), message=None, error=str(exc)), 400

    @blueprint.post("/admin/approvals/<request_id>/decision")
    @authenticated
    @admin_required
    def decide_request(request_id: str):
        try:
            result = service.decide(request_id, _current_user(), request.form.get("decision", ""), request.form.get("note", ""))
            decided_item = result[0] if isinstance(result, tuple) else result
            self_approval = result[1] if isinstance(result, tuple) else False
            partial_notice = ""
            decision = request.form.get("decision", "").strip().upper()
            review_note = request.form.get("note", "").strip()
            record_audit(
                audit_path,
                str(session["iam_user"]),
                "REQUEST_SELF_APPROVED_BREAK_GLASS" if self_approval else "REQUEST_DECIDED",
                "change_request",
                request_id,
                new_values={
                    "decision": decision,
                    "review_note": review_note,
                    "break_glass": self_approval,
                    "authorization_mode": "ADMIN_SELF_APPROVAL" if self_approval else "ADMIN_DECISION",
                },
            )
            if decided_item.status == "REJECTED":
                notifications.create(decided_item.created_by, "REQUEST_REJECTED", "Request rejected", f"Request {request_id[:8]} was rejected by {session['iam_user']}: {review_note}", severity="WARNING", target_route="/requests", entity_type="change_request", entity_id=request_id)
            if decided_item.status == "APPROVED":
                if decided_item.operation_type in {"IMPORT_ROSTER_LOCK", "IMPORT_RSR_SUPPLIER_DETAILS"}:
                    result = employees.apply_approved_import_records(
                        decided_item.payload.get("record_ids", []),
                        str(session["iam_user"]),
                        request_payload=decided_item.payload,
                    )
                    if result["failed"]:
                        failure_text = "; ".join(f"{item['record_id'][:8]}: {item['error']}" for item in result.get("errors", []))
                        record_audit(audit_path, str(session["iam_user"]), "IMPORT_PARTIAL_FAILURE", "change_request", request_id, new_values={"failed": result["failed"], "errors": result.get("errors", [])})
                        failed_ids = {str(item.get("record_id", "")) for item in result.get("errors", []) if item.get("record_id")}
                        failed_previews = [preview for preview in decided_item.payload.get("record_previews", []) if str(preview.get("record_id", "")) in failed_ids]
                        retry_request = service.create(
                            CurrentUser(decided_item.created_by, decided_item.computer_name, tuple(session.get("iam_roles", ()))),
                            decided_item.operation_type,
                            decided_item.entity_id,
                            {
                                **decided_item.payload,
                                "record_ids": sorted(failed_ids),
                                "record_count": len(failed_ids),
                                "record_previews": failed_previews,
                                "retry_of": decided_item.request_id,
                                "previous_errors": result.get("errors", []),
                            },
                            f"Retry failed records from approved request {decided_item.request_id[:8]}.",
                        )
                        record_audit(audit_path, str(session["iam_user"]), "IMPORT_RETRY_REQUEST_CREATED", "change_request", retry_request.request_id, new_values={"retry_of": request_id, "failed": result["failed"]})
                        partial_notice = f" Import approved with {result['failed']} record(s) not promoted: {failure_text}. Follow-up request {retry_request.request_id[:8]} is now waiting for review."
                    if decided_item.operation_type == "IMPORT_ROSTER_LOCK":
                        refreshed = employees.refresh_rsr_matches()
                        if refreshed["reviewed"]:
                            record_audit(audit_path, str(session["iam_user"]), "RSR_MATCHING_REFRESHED", "import_batch", decided_item.entity_id, new_values=refreshed)
                for user in users.list_users():
                    if user.active and {normalize_role(role) for role in user.roles} & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                        notifications.create(user.username, "REQUEST_READY_FOR_PUBLICATION", "Approved request ready for publication", f"Request {request_id[:8]} was approved and is waiting in the Publication Queue.", severity="WARNING", target_route="/admin/publication", entity_type="change_request", entity_id=request_id)
            if decided_item.status == "APPROVED" and decided_item.operation_type == "IMPORT_ROSTER_LOCK":
                message = "Request approved. Roster Lock records created canonical employees and dependent RSR matches were refreshed." + partial_notice
            elif decided_item.status == "APPROVED":
                message = "Request approved and applied to this workstation. Runtime SQLite still requires publication." + partial_notice
            else:
                message = "Request decision recorded."
            return render_template("requests/approval_queue.html", **queue_context(), message=message, error=None)
        except (ValueError, PermissionError) as exc:
            return render_template("requests/approval_queue.html", **queue_context(), message=None, error=str(exc)), 400

    return blueprint
