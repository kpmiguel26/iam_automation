"""
File: iam_automation/interfaces/web/user_routes.py
Purpose: Defines Flask routes for the user routes area.
Responsibilities: Exposes or coordinates: create_user_blueprint, create_identity_blueprint.
Dependencies: flask, application, identity, identity_discovery, domain
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, render_template, request, session

from ...application.user_service import UserService
from ...application.publication_state import mark_publication_pending
from ...application.audit_service import record_audit
from ...application.identity_service import IdentityService
from ...application.role_catalog import ROLE_OPTIONS
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role
from ...identity_discovery import get_pending_discovery, list_pending_discoveries, list_windows_traceability, mark_discovery
from ...domain.users import ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_INACTIVE, ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED, ACCOUNT_STATUS_SUSPENDED


def create_user_blueprint(database_path: Path, *, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("user_admin", __name__, url_prefix="/admin/users")
    service = UserService(database_path)

    def administrator_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR} & {normalize_role(str(role)) for role in session.get("iam_roles", ())}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def render(message: str | None = None, error: str | None = None):
        roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
        return render_template("admin/users.html", users=service.list_users(), message=message, error=error, role_options=[option for option in ROLE_OPTIONS if option.value != ROLE_SUPER_OPERATOR], can_assign_master=ROLE_MASTER_ADMIN in roles, account_statuses=(ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_SUSPENDED, ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED, ACCOUNT_STATUS_INACTIVE))

    @blueprint.get("")
    @administrator_required
    def users():
        return render()

    @blueprint.post("/create")
    @administrator_required
    def create_user():
        try:
            roles = request.form.getlist("roles") or request.form.get("roles", "").split(",")
            if ROLE_MASTER_ADMIN in {normalize_role(role) for role in roles} and ROLE_MASTER_ADMIN not in {normalize_role(role) for role in session.get("iam_roles", ())}:
                return render(error="Only MASTER_ADMIN can assign MASTER_ADMIN."), 403
            service.create_user(request.form.get("username", ""), request.form.get("display_name", ""), request.form.get("password", ""), roles)
            mark_publication_pending(database_path, actor=str(session["iam_user"]), reason="Application user created")
            record_audit(audit_path, str(session["iam_user"]), "APPLICATION_USER_CREATED", "app_user", request.form.get("username", ""), new_values={"roles": roles})
            return render(message="Application user created.")
        except ValueError as exc:
            return render(error=str(exc)), 400

    @blueprint.post("/<username>/update")
    @administrator_required
    def update_user(username: str):
        try:
            roles = request.form.getlist("roles") or request.form.get("roles", "").split(",")
            if ROLE_MASTER_ADMIN in {normalize_role(role) for role in roles} and ROLE_MASTER_ADMIN not in {normalize_role(role) for role in session.get("iam_roles", ())}:
                return render(error="Only MASTER_ADMIN can assign MASTER_ADMIN."), 403
            status = request.form.get("status", ACCOUNT_STATUS_ACTIVE)
            service.update_user(username, display_name=request.form.get("display_name", ""), password=request.form.get("password", ""), roles=roles, active=status == ACCOUNT_STATUS_ACTIVE, status=status)
            mark_publication_pending(database_path, actor=str(session["iam_user"]), reason=f"Application user updated: {username}")
            record_audit(audit_path, str(session["iam_user"]), "APPLICATION_USER_UPDATED", "app_user", username, new_values={"roles": roles, "status": status})
            return render(message=f"Application user updated: {username}")
        except ValueError as exc:
            return render(error=str(exc)), 400

    return blueprint


def create_identity_blueprint(database_path: Path, *, discovery_file: Path | None = None, traceability_directory: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("identity_admin", __name__, url_prefix="/admin/windows-identities")
    service = IdentityService(database_path)

    def administrator_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def render(message: str | None = None, error: str | None = None):
        roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
        pending = list_pending_discoveries(discovery_file) if discovery_file and discovery_file.exists() else []
        return render_template("admin/windows_identities.html", identities=service.list_identities(), traceability=list_windows_traceability(traceability_directory) if traceability_directory else [], pending_discoveries=pending, message=message, error=error, role_options=[option for option in ROLE_OPTIONS if option.value != ROLE_SUPER_OPERATOR], can_assign_master=ROLE_MASTER_ADMIN in roles)

    @blueprint.get("")
    @administrator_required
    def identities():
        return render()

    @blueprint.post("/save")
    @administrator_required
    def save_identity():
        try:
            roles = request.form.getlist("roles") or request.form.get("roles", "").split(",")
            can_assign_master = ROLE_MASTER_ADMIN in {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            service.save_identity(request.form.get("username", ""), request.form.get("display_name", ""), roles, request.form.get("active", "1") == "1", can_assign_master=can_assign_master)
            record_audit(audit_path, str(session["iam_user"]), "WINDOWS_IDENTITY_SAVED", "windows_identity", request.form.get("username", ""), new_values={"roles": roles})
            return render(message="Windows identity saved.")
        except (ValueError, PermissionError) as exc:
            return render(error=str(exc)), 400

    @blueprint.post("/discoveries/<discovery_id>/approve")
    @administrator_required
    def approve_discovery(discovery_id: str):
        if not discovery_file:
            return render(error="Identity discovery storage is not configured."), 400
        discovery = get_pending_discovery(discovery_file, discovery_id)
        if discovery is None:
            return render(error="Identity discovery was not found or was already processed."), 404
        can_assign_master = ROLE_MASTER_ADMIN in {normalize_role(str(role)) for role in session.get("iam_roles", ())}
        try:
            service.save_identity(discovery.username, discovery.username, [discovery.suggested_role], True, can_assign_master=can_assign_master)
            record_audit(audit_path, str(session["iam_user"]), "WINDOWS_IDENTITY_APPROVED", "windows_identity", discovery.username, new_values={"role": discovery.suggested_role})
            mark_discovery(discovery_file, discovery.discovery_id, "APPROVED", str(session["iam_user"]))
            return render(message=f"Windows identity approved: {discovery.username}")
        except (ValueError, PermissionError) as exc:
            return render(error=str(exc)), 400

    return blueprint
#endfile
