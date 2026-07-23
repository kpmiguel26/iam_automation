from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template, request, session, url_for

from ...application.delegation_service import DelegationService
from ...application.audit_service import record_audit
from ...application.import_service import ImportService
from ...application.notification_service import NotificationService
from ...application.publication_service import PublicationService
from ...application.request_service import RequestService
from ...application.governance_service import GovernanceService
from ...application.session_service import SessionService
from ...application.user_service import UserService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, normalize_role
from ...identity_discovery import list_pending_discoveries


def create_admin_blueprint(database_path: Path, *, discovery_file: Path | None = None, local_runtime_path: Path | None = None, published_runtime_path: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("admin", __name__, url_prefix="/admin")
    notifications = NotificationService(database_path)
    delegations = DelegationService(database_path)
    requests = RequestService(database_path)
    publication = PublicationService(database_path)
    governance = GovernanceService(local_runtime_path=local_runtime_path or database_path, published_runtime_path=published_runtime_path or database_path, audit_path=audit_path or database_path.parent / "audit")
    sessions = SessionService(database_path)
    imports = ImportService(database_path)
    users = UserService(database_path)

    def admin_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def master_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if ROLE_MASTER_ADMIN not in roles:
                return "MASTER_ADMIN role required.", 403
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
        notifications.expire(str(session["iam_user"]))
        return render_template("admin/notifications.html", notifications=notifications.list_for_user(str(session["iam_user"])))

    @blueprint.post("/notifications/<notification_id>/read")
    @admin_required
    def mark_notification_read(notification_id: str):
        notifications.mark_read(str(session["iam_user"]), notification_id)
        return redirect(url_for("admin.notification_center"))

    @blueprint.post("/notifications/<notification_id>/resolve")
    @admin_required
    def resolve_notification(notification_id: str):
        notifications.resolve(str(session["iam_user"]), notification_id)
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
                record_audit(audit_path, principal, "DELEGATION_CREATED", "delegation", delegation.delegation_id, new_values={"delegate": delegation.delegate_username, "scope": delegation.scope})
                return redirect(url_for("admin.delegation_center"))
            except ValueError as exc:
                error = str(exc)
        return render_template("admin/delegations.html", delegations=delegations.list_all(), scopes=sorted(DelegationService.ALLOWED_SCOPES), error=error)

    @blueprint.post("/delegations/expire")
    @admin_required
    def expire_delegations():
        expired = delegations.expire_due()
        return render_template("admin/delegations.html", delegations=delegations.list_all(), scopes=sorted(DelegationService.ALLOWED_SCOPES), error=None, message=f"Expired delegations processed: {expired}.")

    @blueprint.post("/delegations/<delegation_id>/revoke")
    @admin_required
    def revoke_delegation(delegation_id: str):
        delegations.revoke(delegation_id)
        record_audit(audit_path, str(session["iam_user"]), "DELEGATION_REVOKED", "delegation", delegation_id)
        return redirect(url_for("admin.delegation_center"))

    @blueprint.route("/imports", methods=["GET", "POST"])
    @admin_required
    def import_center():
        error = None
        message = None
        if request.method == "POST":
            upload = request.files.get("file")
            if not upload or not upload.filename:
                error = "Select a CSV or XLSX file."
            else:
                try:
                    batch = imports.import_bytes(upload.filename, upload.read(), str(session["iam_user"]))
                    message = f"Import {batch.batch_id[:8]} processed: {batch.valid_rows} valid, {batch.quarantine_rows} quarantined."
                except (ValueError, RuntimeError) as exc:
                    error = str(exc)
        return render_template("admin/imports.html", batches=imports.list_batches(), quarantine=imports.list_quarantine(open_only=True), message=message, error=error)

    @blueprint.post("/imports/quarantine/<quarantine_id>/resolve")
    @admin_required
    def resolve_quarantine(quarantine_id: str):
        try:
            imports.resolve_quarantine(quarantine_id, str(session["iam_user"]))
        except ValueError as exc:
            return render_template("admin/imports.html", batches=imports.list_batches(), quarantine=imports.list_quarantine(open_only=True), message=None, error=str(exc)), 400
        return redirect(url_for("admin.import_center"))

    @blueprint.get("/publication")
    @admin_required
    def publication_queue():
        return render_template("requests/publication_queue.html", publications=publication.list_pending())

    @blueprint.get("/governance")
    @master_required
    def governance_center():
        return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events())

    @blueprint.post("/governance/publish")
    @master_required
    def publish_runtime():
        try:
            governance.publish(str(session["iam_user"]), request.form.get("expected_checksum", ""))
            return redirect(url_for("admin.governance_center"))
        except Exception as exc:
            return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events(), error=str(exc)), 400

    @blueprint.post("/governance/restore")
    @master_required
    def restore_runtime():
        try:
            governance.restore(str(session["iam_user"]), request.form.get("backup_name", ""))
            return redirect(url_for("admin.governance_center"))
        except Exception as exc:
            return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events(), error=str(exc)), 400

    @blueprint.get("/security/sessions")
    @master_required
    def session_security():
        return render_template("admin/session_security.html", revocations=sessions.list_recent(), message=None, error=None)

    @blueprint.post("/security/sessions/revoke")
    @master_required
    def revoke_session():
        try:
            sessions.revoke_user(request.form.get("username", ""), str(session["iam_user"]), request.form.get("reason", ""))
            return render_template("admin/session_security.html", revocations=sessions.list_recent(), message="User sessions revoked.", error=None)
        except ValueError as exc:
            return render_template("admin/session_security.html", revocations=sessions.list_recent(), message=None, error=str(exc)), 400

    return blueprint
