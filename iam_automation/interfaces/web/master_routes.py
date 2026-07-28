from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, send_file, session, url_for

from ...application.master_admin_service import MasterAdminService
from ...application.role_catalog import ROLE_OPTIONS
from ...application.temporary_super_operator_service import TemporarySuperOperatorService
from ...application.user_service import UserService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, normalize_role


def create_master_blueprint(database_path: Path, audit_path: Path) -> Blueprint:
    blueprint = Blueprint("master_admin", __name__, url_prefix="/admin/master")
    service = MasterAdminService(database_path, audit_path)
    temporary_access = TemporarySuperOperatorService(database_path, audit_path)
    users = UserService(database_path)

    def master_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            if ROLE_MASTER_ADMIN not in roles:
                return "MASTER_ADMIN role required.", 403
            return view(*args, **kwargs)

        return wrapped

    def render_admins(message=None, error=None):
        return render_template(
            "admin/master_admins.html",
            administrators=service.list_administrators(),
            role_options=[option for option in ROLE_OPTIONS if option.value in {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}],
            message=message,
            error=error,
        )

    @blueprint.get("/administrators")
    @master_required
    def administrators():
        return render_admins()

    @blueprint.get("/roles")
    @master_required
    def roles():
        permissions = {
            "Manage administrators": {ROLE_MASTER_ADMIN},
            "Manage application users": {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN},
            "Review approval queue": {"REVIEWER", ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN},
            "Operate publication": {"WRITER", ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN},
            "Temporary operational superuser": {"SUPER_OPERATOR"},
            "Configure global security": {ROLE_MASTER_ADMIN},
            "Export audit evidence": {"AUDITOR", ROLE_MASTER_ADMIN},
        }
        return render_template("admin/master_roles.html", role_options=ROLE_OPTIONS, permissions=permissions)

    @blueprint.route("/temporary-super-operator", methods=["GET", "POST"])
    @master_required
    def temporary_super_operator():
        error = None
        message = None
        if request.method == "POST":
            try:
                temporary_access.grant(
                    request.form.get("username", ""),
                    request.form.get("starts_at_utc", ""),
                    request.form.get("expires_at_utc", ""),
                    request.form.get("reason", ""),
                    str(session["iam_user"]),
                )
                message = "Temporary Super Operator access granted and audited."
            except (ValueError, PermissionError) as exc:
                error = str(exc)
        return render_template(
            "admin/temporary_super_operator.html",
            users=[user for user in users.list_users() if user.active and user.status == "ACTIVE"],
            elevations=temporary_access.list_all(),
            message=message,
            error=error,
        )

    @blueprint.post("/temporary-super-operator/<elevation_id>/revoke")
    @master_required
    def revoke_temporary_super_operator(elevation_id: str):
        temporary_access.revoke(elevation_id, str(session["iam_user"]))
        return redirect(url_for("master_admin.temporary_super_operator"))

    @blueprint.post("/administrators/save")
    @master_required
    def save_administrator():
        try:
            roles = request.form.getlist("roles")
            service.save_administrator(
                request.form.get("username", ""),
                request.form.get("display_name", ""),
                request.form.get("password", ""),
                roles,
                request.form.get("active", "1") == "1",
            )
            return render_admins(message="Administrator account saved.")
        except (ValueError, PermissionError) as exc:
            return render_admins(error=str(exc)), 400

    @blueprint.route("/settings", methods=["GET", "POST"])
    @master_required
    def settings():
        error = None
        message = None
        if request.method == "POST":
            try:
                values = {
                    "approval_sla_hours": {
                        "CREATE_EMPLOYEE": request.form.get("sla_create", "24"),
                        "UPDATE_EMPLOYEE": request.form.get("sla_update", "16"),
                        "DEACTIVATE_EMPLOYEE": request.form.get("sla_deactivate", "8"),
                    },
                    "strict_identity_gate": request.form.get("strict_identity_gate") == "1",
                    "break_glass_enabled": request.form.get("break_glass_enabled") == "1",
                    "temporary_super_operator_enabled": request.form.get("temporary_super_operator_enabled") == "1",
                }
                service.save_settings(values, str(session["iam_user"]))
                message = "Global settings saved."
            except (ValueError, PermissionError) as exc:
                error = str(exc)
        return render_template("admin/master_settings.html", settings=service.settings(), message=message, error=error)

    @blueprint.post("/break-glass")
    @master_required
    def break_glass():
        try:
            service.break_glass(str(session["iam_user"]), request.form.get("reason", ""), request.form.get("operation", ""))
            return redirect(url_for("master_admin.settings", message="Break-glass operation authorized and audited."))
        except (ValueError, PermissionError) as exc:
            return render_template("admin/master_settings.html", settings=service.settings(), message=None, error=str(exc)), 400

    @blueprint.get("/audit")
    @master_required
    def audit():
        return render_template("admin/master_audit.html", events=service.audit_events())

    @blueprint.get("/audit/export")
    @master_required
    def export_audit():
        destination = audit_path / "exports" / "audit_export.json"
        service.export_audit(destination)
        return send_file(destination, as_attachment=True, download_name="iam_audit_export.json", mimetype="application/json")

    @blueprint.post("/audit/archive")
    @master_required
    def archive_audit():
        service.archive_audit(str(session["iam_user"]))
        return redirect(url_for("master_admin.audit"))

    return blueprint
