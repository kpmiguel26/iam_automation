from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.delegation_service import DelegationService
from ...application.notification_service import NotificationService
from ...application.publication_service import PublicationService
from ...application.request_service import RequestService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, normalize_role
from ...identity_discovery import list_pending_discoveries


def create_admin_blueprint(database_path: Path, *, discovery_file: Path | None = None) -> Blueprint:
    blueprint = Blueprint("admin", __name__, url_prefix="/admin")
    notifications = NotificationService(database_path)
    delegations = DelegationService(database_path)
    requests = RequestService(database_path)
    publication = PublicationService(database_path)

    def admin_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    @blueprint.get("")
    @admin_required
    def home():
        username = str(session.get("iam_user", ""))
        pending = list_pending_discoveries(discovery_file) if discovery_file and discovery_file.exists() else []
        return render_template("admin/control_center.html", username=username, roles=tuple(session.get("iam_roles", ())), unread_count=notifications.unread_count(username), delegations=delegations.list_active(), pending_discoveries=pending, message=None, error=None)

    @blueprint.get("/notifications")
    @admin_required
    def notification_center():
        return render_template("admin/notifications.html", notifications=notifications.list_for_user(str(session["iam_user"])))

    @blueprint.post("/notifications/<notification_id>/read")
    @admin_required
    def mark_notification_read(notification_id: str):
        notifications.mark_read(str(session["iam_user"]), notification_id)
        return redirect(url_for("admin.notification_center"))

    @blueprint.route("/delegations", methods=["GET", "POST"])
    @admin_required
    def delegation_center():
        error = None
        if request.method == "POST":
            try:
                principal = str(session["iam_user"])
                delegation = delegations.create(principal, request.form.get("delegate_username", ""), request.form.get("scope", ""), request.form.get("starts_at_utc", ""), request.form.get("expires_at_utc", ""), request.form.get("reason", ""), principal)
                if delegation.scope in {"APPROVALS", "FULL_OPERATIONS"}:
                    requests.reassign_for_delegation(principal, delegation.delegate_username, principal, f"Delegation {delegation.delegation_id[:8]} activated")
                notifications.create(delegation.delegate_username, "DELEGATION_CREATED", "Delegation assigned", f"You have temporary {delegation.scope} access from {delegation.principal_username}.", severity="WARNING", target_route="/admin/delegations")
                return redirect(url_for("admin.delegation_center"))
            except ValueError as exc:
                error = str(exc)
        return render_template("admin/delegations.html", delegations=delegations.list_active(), scopes=sorted(DelegationService.ALLOWED_SCOPES), error=error)

    @blueprint.post("/delegations/<delegation_id>/revoke")
    @admin_required
    def revoke_delegation(delegation_id: str):
        delegations.revoke(delegation_id)
        return redirect(url_for("admin.delegation_center"))

    @blueprint.get("/publication")
    @admin_required
    def publication_queue():
        return render_template("requests/publication_queue.html", publications=publication.list_pending())

    return blueprint
