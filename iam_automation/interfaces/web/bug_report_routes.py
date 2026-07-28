from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, session, redirect, url_for

from ...application.bug_report_service import BUG_SEVERITIES, BUG_STATUSES, BugReportService
from ...application.notification_service import NotificationService
from ...application.user_service import UserService
from ...application.audit_service import record_audit
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role


def create_bug_report_blueprint(database_path: Path, sharepoint_root: Path) -> Blueprint:
    blueprint = Blueprint("bug_reports", __name__, url_prefix="/bug-reports")
    service = BugReportService(sharepoint_root)
    notifications = NotificationService(database_path)
    users = UserService(database_path)

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    @blueprint.route("", methods=["GET", "POST"])
    @authenticated
    def index():
        username = str(session["iam_user"])
        is_admin = bool(session.get("is_admin"))
        error = None
        message = None
        if request.method == "POST":
            try:
                bug = service.create(title=request.form.get("title", ""), description=request.form.get("description", ""), severity=request.form.get("severity", ""), page=request.form.get("page", ""), reporter=username, computer=request.form.get("computer", "local-web"))
                for user in users.list_users():
                    if user.active and {normalize_role(role) for role in user.roles} & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                        notifications.create(user.username, "BUG_REPORT_CREATED", "New bug report", f"{bug.severity} bug {bug.bug_id[:8]} was reported by {bug.reporter}.", severity="WARNING", target_route="/bug-reports", entity_type="bug_report", entity_id=bug.bug_id)
                record_audit(sharepoint_root / "audit", username, "BUG_REPORT_CREATED", "bug_report", bug.bug_id, new_values={"severity": bug.severity, "page": bug.page})
                message = f"Bug report {bug.bug_id[:8]} submitted to SharePoint."
            except ValueError as exc:
                error = str(exc)
        return render_template("bug_reports/index.html", bugs=service.list_for_user(username, is_admin=is_admin), all_bugs=is_admin, severities=BUG_SEVERITIES, statuses=BUG_STATUSES, users=users.list_users(), error=error, message=message)

    @blueprint.post("/<bug_id>/update")
    @admin_required
    def update(bug_id: str):
        try:
            updated = service.update(bug_id, status=request.form.get("status", ""), assigned_to=request.form.get("assigned_to", ""), resolution=request.form.get("resolution", ""))
        except ValueError as exc:
            return str(exc), 400
        actor = str(session["iam_user"])
        record_audit(sharepoint_root / "audit", actor, "BUG_REPORT_UPDATED", "bug_report", updated.bug_id, new_values={"status": updated.status, "assigned_to": updated.assigned_to, "resolution": updated.resolution})
        notifications.create(updated.reporter, "BUG_REPORT_UPDATED", "Bug report updated", f"Your bug report {updated.bug_id[:8]} is now {updated.status.replace('_', ' ').title()}.", severity="INFO", target_route="/bug-reports", entity_type="bug_report", entity_id=updated.bug_id)
        return redirect(url_for("bug_reports.index"))

    return blueprint
