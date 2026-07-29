from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template, request, send_file, session, url_for

from ...application.delegation_service import DelegationService
from ...application.employee_service import EmployeeService
from ...application.audit_service import record_audit
from ...application.import_service import ImportService
from ...application.notification_service import NotificationService
from ...application.publication_service import PublicationService
from ...application.salesforce_export_service import SalesforceExportService
from ...application.request_service import RequestService
from ...application.shared_request_service import SharedRequestService
from ...application.governance_service import GovernanceService
from ...application.publication_state import publication_pending
from ...application.session_service import SessionService
from ...application.user_service import UserService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role
from ...identity_discovery import list_pending_discoveries


def create_admin_blueprint(database_path: Path, *, discovery_file: Path | None = None, sharepoint_root: Path | None = None, local_runtime_path: Path | None = None, published_runtime_path: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("admin", __name__, url_prefix="/admin")
    notifications = NotificationService(database_path)
    delegations = DelegationService(database_path)
    requests = RequestService(database_path)
    shared_requests = SharedRequestService(sharepoint_root) if sharepoint_root else None
    publication = PublicationService(database_path)
    governance = GovernanceService(local_runtime_path=local_runtime_path or database_path, published_runtime_path=published_runtime_path or database_path, audit_path=audit_path or database_path.parent / "audit")
    sessions = SessionService(database_path)
    imports = ImportService(database_path)
    users = UserService(database_path)
    employees = EmployeeService(database_path)
    salesforce = SalesforceExportService(database_path, audit_path=audit_path)

    def admin_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR}:
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

    def database_publish_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(role) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                return "APPLICATION_ADMIN or MASTER_ADMIN role required.", 403
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
        username = str(session["iam_user"])
        notifications.expire(username)
        items = notifications.list_for_user(username)
        status = request.args.get("status", "ALL").upper()
        severity = request.args.get("severity", "ALL").upper()
        if status != "ALL":
            items = [item for item in items if item.status == status]
        if severity != "ALL":
            items = [item for item in items if item.severity == severity]
        return render_template("admin/notifications.html", notifications=items, filters={"status": status, "severity": severity}, unread_count=notifications.unread_count(username))

    @blueprint.post("/notifications/<notification_id>/read")
    @admin_required
    def mark_notification_read(notification_id: str):
        notifications.mark_read(str(session["iam_user"]), notification_id)
        return redirect(url_for("admin.notification_center", notice="Notification marked as read.", notice_type="success"))

    @blueprint.post("/notifications/<notification_id>/resolve")
    @admin_required
    def resolve_notification(notification_id: str):
        notifications.resolve(str(session["iam_user"]), notification_id)
        return redirect(url_for("admin.notification_center", notice="Notification resolved.", notice_type="success"))

    @blueprint.post("/notifications/read-all")
    @admin_required
    def mark_all_notifications_read():
        count = notifications.mark_all_read(str(session["iam_user"]))
        return redirect(url_for("admin.notification_center", notice=f"{count} notification(s) marked as read.", notice_type="success"))

    @blueprint.get("/notifications/<notification_id>/open")
    @admin_required
    def open_notification(notification_id: str):
        username = str(session["iam_user"])
        item = next((item for item in notifications.list_for_user(username) if item.notification_id == notification_id), None)
        if item is None:
            return redirect(url_for("admin.notification_center", notice="Notification was not found.", notice_type="warning"))
        notifications.mark_read(username, notification_id)
        return redirect(item.target_route or url_for("admin.notification_center"))

    @blueprint.route("/delegations", methods=["GET", "POST"])
    @admin_required
    def delegation_center():
        error = None
        principal = str(session.get("iam_user", ""))
        delegation_users = [user for user in users.list_users() if user.active and user.username.lower() != principal.lower()]
        if request.method == "POST":
            try:
                delegation = delegations.create(principal, request.form.get("delegate_username", ""), request.form.get("scope", ""), request.form.get("starts_at_utc", ""), request.form.get("expires_at_utc", ""), request.form.get("reason", ""), principal)
                if delegation.scope in {"APPROVALS", "FULL_OPERATIONS"}:
                    requests.reassign_for_delegation(principal, delegation.delegate_username, principal, f"Delegation {delegation.delegation_id[:8]} activated")
                notifications.create(delegation.delegate_username, "DELEGATION_CREATED", "Delegation assigned", f"You have temporary {delegation.scope} access from {delegation.principal_username}.", severity="WARNING", target_route="/admin/delegations")
                record_audit(audit_path, principal, "DELEGATION_CREATED", "delegation", delegation.delegation_id, new_values={"delegate": delegation.delegate_username, "scope": delegation.scope})
                return redirect(url_for("admin.delegation_center"))
            except ValueError as exc:
                error = str(exc)
        return render_template("admin/delegations.html", delegations=delegations.list_all(), scopes=sorted(DelegationService.ALLOWED_SCOPES), delegation_users=delegation_users, error=error)

    @blueprint.post("/delegations/expire")
    @admin_required
    def expire_delegations():
        expired = delegations.expire_due()
        principal = str(session.get("iam_user", ""))
        delegation_users = [user for user in users.list_users() if user.active and user.username.lower() != principal.lower()]
        return render_template("admin/delegations.html", delegations=delegations.list_all(), scopes=sorted(DelegationService.ALLOWED_SCOPES), delegation_users=delegation_users, error=None, message=f"Expired delegations processed: {expired}.")

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
        return render_template("admin/imports.html", batches=imports.list_batches(), quarantine=imports.list_quarantine(open_only=True), staged_records=employees.list_staged_records(), message=message, error=error)

    @blueprint.post("/imports/records/<record_id>/promote")
    @admin_required
    def promote_ingestion_record(record_id: str):
        try:
            worker_id = employees.promote_ingestion_record(record_id, str(session["iam_user"]))
            return redirect(url_for("employees.employee_detail", worker_id=worker_id))
        except ValueError as exc:
            return render_template("admin/imports.html", batches=imports.list_batches(), quarantine=imports.list_quarantine(open_only=True), staged_records=employees.list_staged_records(), message=None, error=str(exc)), 400

    @blueprint.post("/imports/records/promote-all")
    @admin_required
    def promote_all_ingestion_records():
        try:
            result = employees.promote_all_staged_records(str(session["iam_user"]))
            message = (
                f"Bulk promotion complete: {result['processed']} processed, "
                f"{result['created']} new workers, {result['reused']} existing workers reused, "
                f"{result['failed']} failed."
            )
            if result["failed"]:
                message += " Review the failed staged records before retrying."
            return render_template(
                "admin/imports.html",
                batches=imports.list_batches(),
                quarantine=imports.list_quarantine(open_only=True),
                staged_records=employees.list_staged_records(),
                message=message,
                error=None,
            )
        except (ValueError, RuntimeError) as exc:
            return render_template(
                "admin/imports.html",
                batches=imports.list_batches(),
                quarantine=imports.list_quarantine(open_only=True),
                staged_records=employees.list_staged_records(),
                message=None,
                error=str(exc),
            ), 400

    @blueprint.post("/imports/quarantine/<quarantine_id>/resolve")
    @admin_required
    def resolve_quarantine(quarantine_id: str):
        try:
            imports.resolve_quarantine(quarantine_id, str(session["iam_user"]))
        except ValueError as exc:
            return render_template("admin/imports.html", batches=imports.list_batches(), quarantine=imports.list_quarantine(open_only=True), staged_records=employees.list_staged_records(), message=None, error=str(exc)), 400
        return redirect(url_for("admin.import_center"))

    @blueprint.get("/publication")
    @admin_required
    def publication_queue():
        return render_template("requests/publication_queue.html", publications=publication.list_pending(), approved_requests=shared_requests.list_approved() if shared_requests else [])

    @blueprint.get("/exports/salesforce")
    @admin_required
    def export_salesforce():
        try:
            destination_folder = (local_runtime_path or database_path).parent / "generated_templates"
            if audit_path and audit_path.parent.name:
                destination_folder = audit_path.parent / "generated_templates"
            destination = salesforce.generate(destination_folder, str(session["iam_user"]))
            return send_file(destination, as_attachment=True, download_name=destination.name, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except ValueError as exc:
            return render_template("admin/control_center.html", username=str(session.get("iam_user", "")), roles=tuple(session.get("iam_roles", ())), unread_count=notifications.unread_count(str(session.get("iam_user", ""))), delegations=delegations.list_active(), pending_discoveries=[], message=None, error=str(exc)), 400

    @blueprint.get("/templates")
    @admin_required
    def template_center():
        try:
            columns = salesforce.template_columns()
            preview_headers, preview_rows = salesforce.template_preview()
            template_checksum = salesforce.template_checksum()
            template_error = None
        except ValueError as exc:
            columns = []
            preview_headers, preview_rows, template_checksum = [], [], ""
            template_error = str(exc)
        return render_template("admin/templates.html", columns=columns, preview_headers=preview_headers, preview_rows=preview_rows, template_checksum=template_checksum, approved_row_count=salesforce.approved_row_count() if not template_error else 0, template_error=template_error)

    @blueprint.get("/templates/salesforce/download")
    @admin_required
    def download_salesforce_template():
        if not salesforce.template_path.is_file():
            return render_template("admin/templates.html", columns=[], preview_headers=[], preview_rows=[], template_checksum="", approved_row_count=0, template_error=f"Salesforce template was not found: {salesforce.template_path}"), 404
        return send_file(salesforce.template_path, as_attachment=True, download_name=salesforce.template_path.name, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @blueprint.get("/governance")
    @database_publish_required
    def governance_center():
        return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events(), publication_pending=publication_pending(local_runtime_path or database_path), error=None)

    @blueprint.post("/governance/publish")
    @database_publish_required
    def publish_runtime():
        roles = {normalize_role(role) for role in session.get("iam_roles", ())}
        if ROLE_SUPER_OPERATOR in roles and not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
            return "SUPER_OPERATOR cannot publish the runtime database.", 403
        try:
            governance.publish(str(session["iam_user"]), request.form.get("expected_checksum", ""))
            return redirect(url_for("admin.governance_center"))
        except Exception as exc:
            return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events(), publication_pending=publication_pending(local_runtime_path or database_path), error=str(exc)), 400

    @blueprint.post("/governance/restore")
    @master_required
    def restore_runtime():
        if ROLE_SUPER_OPERATOR in {normalize_role(role) for role in session.get("iam_roles", ())}:
            return "SUPER_OPERATOR cannot restore the runtime database.", 403
        try:
            governance.restore(str(session["iam_user"]), request.form.get("backup_name", ""))
            return redirect(url_for("admin.governance_center"))
        except Exception as exc:
            return render_template("admin/governance.html", checksum=governance.published_checksum(), backups=governance.list_backups(), events=governance.list_audit_events(), publication_pending=publication_pending(local_runtime_path or database_path), error=str(exc)), 400

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
