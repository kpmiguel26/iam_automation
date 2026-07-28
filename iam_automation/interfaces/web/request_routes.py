from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, session

from ...application.request_service import OPERATION_OPTIONS, RequestService
from ...application.audit_service import record_audit
from ...application.user_service import UserService
from ...identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_REVIEWER, ROLE_SUPER_OPERATOR, normalize_role


def _current_user() -> CurrentUser:
    return CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))


def create_request_blueprint(database_path: Path, *, sharepoint_root: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("requests", __name__)
    service = RequestService(database_path)
    users = UserService(database_path)

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
            roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Reviewer role required.", 403
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
        allowed = {ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}
        return [user for user in users.list_users() if user.active and allowed & set(user.roles)]

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
                service.create(_current_user(), request.form.get("operation_type", ""), request.form.get("entity_id", ""), payload, request.form.get("reason", ""))
                if sharepoint_root:
                    service.export_pending_for_user(str(session["iam_user"]), sharepoint_root / "requests" / "pending")
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
        return render_template("requests/approval_queue.html", requests=service.list_requests(queue=True), reviewers=reviewer_accounts(), message=None, error=None)

    @blueprint.post("/admin/approvals/<request_id>/assign")
    @authenticated
    @admin_required
    def assign_request(request_id: str):
        try:
            item = service.assign(request_id, request.form.get("reviewer", ""), str(session["iam_user"]), request.form.get("reason", ""))
            record_audit(audit_path, str(session["iam_user"]), "REQUEST_ASSIGNED", "change_request", request_id, new_values={"reviewer": item.assigned_to})
            return render_template("requests/approval_queue.html", requests=service.list_requests(queue=True), reviewers=reviewer_accounts(), message="Reviewer assigned.", error=None)
        except (ValueError, PermissionError) as exc:
            return render_template("requests/approval_queue.html", requests=service.list_requests(queue=True), reviewers=reviewer_accounts(), message=None, error=str(exc)), 400

    @blueprint.post("/admin/approvals/<request_id>/decision")
    @authenticated
    @reviewer_required
    def decide_request(request_id: str):
        try:
            service.decide(request_id, _current_user(), request.form.get("decision", ""), request.form.get("note", ""))
            record_audit(audit_path, str(session["iam_user"]), "REQUEST_DECIDED", "change_request", request_id, new_values={"decision": request.form.get("decision", "")})
            return render_template("requests/approval_queue.html", requests=service.list_requests(queue=True), reviewers=reviewer_accounts(), message="Request decision recorded.", error=None)
        except (ValueError, PermissionError) as exc:
            return render_template("requests/approval_queue.html", requests=service.list_requests(queue=True), reviewers=reviewer_accounts(), message=None, error=str(exc)), 400

    return blueprint
