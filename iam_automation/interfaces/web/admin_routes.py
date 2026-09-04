"""
File: iam_automation/interfaces/web/admin_routes.py
Purpose: Defines Flask routes for the admin routes area.
Responsibilities: Exposes or coordinates: create_admin_blueprint.
Dependencies: flask, application, database, identity, identity_discovery
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import sqlite3
from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template, request, send_file, session, url_for

from ...application.delegation_service import DelegationService
from ...application.employee_service import EmployeeService
from ...application.employee_reset_service import EmployeeResetService
from ...application.audit_service import record_audit
from ...application.import_service import ImportService
from ...application.notification_service import NotificationService
from ...application.business_rule_service import BusinessRuleService
from ...application.file_watch_service import load_watcher_health
from ...application.publication_service import PublicationService
from ...application.salesforce_export_service import SalesforceExportService
from ...application.request_service import RequestService
from ...application.shared_request_service import SharedRequestService
from ...application.governance_service import GovernanceService
from ...application.publication_state import publication_pending
from ...application.publication_state import mark_publication_pending
from ...database.migration_runner import current_database_revision
from ...application.session_service import SessionService
from ...application.user_service import UserService
from ...identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_SUPER_OPERATOR, normalize_role
from ...identity_discovery import list_pending_discoveries


def create_admin_blueprint(database_path: Path, *, discovery_file: Path | None = None, sharepoint_root: Path | None = None, local_runtime_path: Path | None = None, published_runtime_path: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("admin", __name__, url_prefix="/admin")
    notifications = NotificationService(database_path, sharepoint_root=sharepoint_root)
    delegations = DelegationService(database_path)
    requests = RequestService(database_path)
    shared_requests = SharedRequestService(sharepoint_root) if sharepoint_root else None
    publication = PublicationService(database_path)
    governance = GovernanceService(local_runtime_path=local_runtime_path or database_path, published_runtime_path=published_runtime_path or database_path, audit_path=audit_path or database_path.parent / "audit")
    sessions = SessionService(database_path)
    imports = ImportService(database_path)
    rules = BusinessRuleService(database_path)
    users = UserService(database_path)
    employees = EmployeeService(database_path)
    employee_reset = EmployeeResetService(
        local_runtime_path or database_path,
        audit_path=audit_path or database_path.parent / "audit",
        backup_directory=(published_runtime_path or database_path).parent / "backups",
    )
    salesforce = SalesforceExportService(database_path, audit_path=audit_path)
    automatic_source_types = {"ROSTER_LOCK", "MASTER_ROSTER", "RSR_SUPPLIER_WORKER_DETAILS", "ACCESSNOW"}

    def imports_page_context(*, message=None, error=None):
        batches = imports.list_batches()
        automatic_batch_ids = {
            batch.batch_id for batch in batches
            if batch.source_type in automatic_source_types
        }
        return {
            "batches": [
                batch for batch in batches
                if batch.source_type not in automatic_source_types
            ],
            "quarantine": [
                item for item in imports.list_quarantine(open_only=True)
                if item["batch_id"] not in automatic_batch_ids
            ],
            # Automatic source records are reviewed under Source Updates.
            "staged_records": [],
            "message": message,
            "error": error,
        }

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

    def render_governance(*, error=None, message=None, reset_result=None):
        return render_template(
            "admin/governance.html",
            checksum=governance.published_checksum(),
            schema_revision=current_database_revision(local_runtime_path or database_path),
            backups=governance.list_backups(),
            events=governance.list_audit_events(),
            publication_pending=publication_pending(local_runtime_path or database_path),
            error=error,
            message=message,
            reset_result=reset_result,
        )

    @blueprint.get("")
    @admin_required
    def home():
        username = str(session.get("iam_user", ""))
        pending = list_pending_discoveries(discovery_file) if discovery_file and discovery_file.exists() else []
        return render_template("admin/control_center.html", username=username, roles=tuple(session.get("iam_roles", ())), unread_count=notifications.unread_count(username), delegations=delegations.list_active(), pending_discoveries=pending, watcher_health=load_watcher_health(database_path), message=None, error=None)

    @blueprint.get("/notifications")
    @admin_required
    def notification_center():
        status = request.args.get("status", "ALL").upper()
        severity = request.args.get("severity", "ALL").upper()
        return redirect(url_for("notifications_page", status=status, severity=severity))

    @blueprint.get("/business-rule-findings")
    @admin_required
    def business_rule_findings():
        status = request.args.get("status", "OPEN").upper()
        severity = request.args.get("severity", "ALL").upper()
        return render_template("admin/business_rule_findings.html", findings=rules.list_findings(status=status, severity=severity), status=status, severity=severity, severities=BusinessRuleService.ALLOWED_SEVERITIES, message=request.args.get("notice"), error=None)

    @blueprint.post("/business-rule-findings/<finding_id>/status")
    @admin_required
    def business_rule_finding_status(finding_id: str):
        try:
            status = request.form.get("status", "").upper()
            note = request.form.get("note", "")
            rules.update_finding(finding_id, status=status, actor=str(session["iam_user"]), note=note)
            record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_FINDING_STATUS_CHANGED", "rule_finding", finding_id, new_values={"status": status, "note": note})
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_business_finding_row.html", finding=next((item for item in rules.list_findings(status="ALL") if item.finding_id == finding_id), None))
            return redirect(url_for("admin.business_rule_findings", notice="Finding updated."))
        except ValueError as exc:
            return redirect(url_for("admin.business_rule_findings", notice=str(exc)))

    @blueprint.route("/business-rules", methods=["GET", "POST"])
    @admin_required
    def business_rules():
        error = None
        message = None
        if request.method == "POST":
            try:
                rule_id = rules.create_rule(name=request.form.get("name", ""), description=request.form.get("description", ""), field=request.form.get("field", ""), operator=request.form.get("operator", ""), value=request.form.get("value", ""), severity=request.form.get("severity", "WARNING"), actor=str(session["iam_user"]))
                mark_publication_pending(database_path, actor=str(session["iam_user"]), reason="Business rule created")
                record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_CREATED", "business_rule", rule_id, new_values={"name": request.form.get("name", ""), "field": request.form.get("field", ""), "operator": request.form.get("operator", ""), "severity": request.form.get("severity", "WARNING")})
                message = "Rule created as DRAFT. Activate it after reviewing the condition."
            except ValueError as exc:
                error = str(exc)
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=message, error=error)
        return render_template("admin/business_rules.html", rules=rules.list_rules(), operators=BusinessRuleService.ALLOWED_OPERATORS, severities=BusinessRuleService.ALLOWED_SEVERITIES, message=message or request.args.get("notice"), error=error)

    @blueprint.post("/business-rules/<rule_id>/status")
    @admin_required
    def business_rule_status(rule_id: str):
        try:
            status = request.form.get("status", "").upper()
            rules.set_status(rule_id, status)
            mark_publication_pending(database_path, actor=str(session["iam_user"]), reason=f"Business rule status changed: {status}")
            finding_count = rules.evaluate_all_batches() if status == "ACTIVE" else 0
            record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_STATUS_CHANGED", "business_rule", rule_id, new_values={"status": status})
            notice = f"Rule {status.lower()}. Historical batches evaluated: {finding_count} new finding(s)." if status == "ACTIVE" else "Rule disabled. Existing findings were preserved."
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=notice, error=None)
            return redirect(url_for("admin.business_rules", notice=notice))
        except ValueError as exc:
            return render_template("admin/business_rules.html", rules=rules.list_rules(), operators=BusinessRuleService.ALLOWED_OPERATORS, severities=BusinessRuleService.ALLOWED_SEVERITIES, message=None, error=str(exc)), 400

    @blueprint.post("/notifications/<notification_id>/read")
    @admin_required
    def mark_notification_read(notification_id: str):
        notifications.mark_read(str(session["iam_user"]), notification_id)
        return redirect(url_for("notifications_page", notice="Notification marked as read.", notice_type="success"))

    @blueprint.post("/notifications/<notification_id>/resolve")
    @admin_required
    def resolve_notification(notification_id: str):
        notifications.resolve(str(session["iam_user"]), notification_id)
        return redirect(url_for("notifications_page", notice="Notification resolved.", notice_type="success"))

    @blueprint.post("/notifications/read-all")
    @admin_required
    def mark_all_notifications_read():
        count = notifications.mark_all_read(str(session["iam_user"]))
        return redirect(url_for("notifications_page", notice=f"{count} notification(s) marked as read.", notice_type="success"))

    @blueprint.get("/notifications/<notification_id>/open")
    @admin_required
    def open_notification(notification_id: str):
        username = str(session["iam_user"])
        item = next((item for item in notifications.list_for_user(username) if item.notification_id == notification_id), None)
        if item is None:
            return redirect(url_for("notifications_page", notice="Notification was not found.", notice_type="warning"))
        notifications.mark_read(username, notification_id)
        return redirect(item.target_route or url_for("notifications_page"))

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
                    finding_count = rules.evaluate_batch(batch.batch_id)
                    message = f"Import {batch.batch_id[:8]} processed: {batch.valid_rows} valid, {batch.quarantine_rows} quarantined. {finding_count} rule finding(s) created."
                except (ValueError, RuntimeError) as exc:
                    error = str(exc)
        return render_template("admin/imports.html", **imports_page_context(message=message, error=error))

    @blueprint.post("/imports/records/<record_id>/promote")
    @admin_required
    def promote_ingestion_record(record_id: str):
        try:
            worker_id = employees.promote_ingestion_record(record_id, str(session["iam_user"]))
            return redirect(url_for("employees.employee_detail", worker_id=worker_id))
        except ValueError as exc:
            return render_template("admin/imports.html", **imports_page_context(error=str(exc))), 400

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
            return render_template("admin/imports.html", **imports_page_context(message=message))
        except (ValueError, RuntimeError) as exc:
            return render_template("admin/imports.html", **imports_page_context(error=str(exc))), 400

    @blueprint.post("/imports/request-approval")
    @admin_required
    def request_import_approval():
        if shared_requests is None:
            return render_template("admin/imports.html", **imports_page_context(error="Automatic source files are reviewed under Source Updates.")), 400
        staged = [item for item in employees.list_staged_records() if item["status"] == "STAGED" and (item["source_system"] != "RSR_SUPPLIER_WORKER_DETAILS" or item["match_status"] in {"MATCHED", "UNMATCHED"})]
        if not staged:
            return redirect(url_for("admin.import_center", notice="There are no staged records waiting for approval.", notice_type="info"))
        try:
            actor = str(session["iam_user"])
            groups = {
                "IMPORT_RSR_SUPPLIER_DETAILS": [item for item in staged if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS"],
                "IMPORT_ACCESSNOW": [item for item in staged if item["source_system"] == "ACCESSNOW"],
                "IMPORT_ROSTER_LOCK": [item for item in staged if item["source_system"] not in {"RSR_SUPPLIER_WORKER_DETAILS", "ACCESSNOW"}],
            }
            created_requests = []
            for operation_type, items in groups.items():
                if not items:
                    continue
                batch_ids = sorted({item["batch_id"] for item in items})
                request_item = shared_requests.create(
                    CurrentUser(actor, "local-web", tuple(session.get("iam_roles", ()))),
                    operation_type,
                    batch_ids[0] if len(batch_ids) == 1 else "MULTIPLE_BATCHES",
                    {"batch_ids": batch_ids, "record_ids": [item["record_id"] for item in items], "record_count": len(items), "source_system": items[0]["source_system"], "record_previews": employees.request_previews([item["record_id"] for item in items])},
                    "Review and approve the staged source import before applying it to canonical employees." if operation_type == "IMPORT_ROSTER_LOCK" else "Review and approve Fieldglass details to enrich matched Employees or create approved new Employee records.",
                )
                created_requests.append(request_item)
                notifications.notify_request_reviewers(
                    request_item.request_id,
                    request_item.operation_type,
                    request_item.created_by,
                    record_count=len(items),
                )
                record_audit(audit_path, actor, "IMPORT_REQUEST_CREATED", "import_batch", request_item.entity_id, new_values={"request_id": request_item.request_id, "record_count": len(items), "source_system": items[0]["source_system"]})
            ids = ", ".join(item.request_id[:8] for item in created_requests)
            return redirect(url_for("admin.import_center", notice=f"Import approval request(s) {ids} created for {len(staged)} record(s).", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return render_template("admin/imports.html", **imports_page_context(error=str(exc))), 400

    @blueprint.post("/imports/refresh-rsr-matches")
    @admin_required
    def refresh_rsr_matches():
        try:
            result = employees.refresh_rsr_matches()
            message = f"RSR matching refreshed: {result['matched']} matched, {result['unmatched']} unmatched, {result['ambiguous']} ambiguous, {result['conflicts']} conflict(s), {result.get('vendor_repaired', 0)} vendor label(s) repaired."
            return redirect(url_for("admin.import_center", notice=message, notice_type="success"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin.import_center", notice=f"RSR matching could not be refreshed: {exc}", notice_type="danger"))

    @blueprint.post("/imports/quarantine/<quarantine_id>/resolve")
    @admin_required
    def resolve_quarantine(quarantine_id: str):
        try:
            imports.resolve_quarantine(quarantine_id, str(session["iam_user"]))
        except ValueError as exc:
            return render_template("admin/imports.html", **imports_page_context(error=str(exc))), 400
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
        return render_governance(message=request.args.get("notice"))

    @blueprint.post("/governance/reset-employee-test-data")
    @database_publish_required
    def reset_employee_test_data():
        if request.form.get("confirmation", "").strip() != "RESET EMPLOYEE TEST DATA":
            return render_governance(error="Type RESET EMPLOYEE TEST DATA exactly to confirm this test-data cleanup."), 400
        try:
            result = employee_reset.reset(str(session["iam_user"]), clear_workflow_records=True)
            return render_governance(
                message="Employee and import test data was cleared locally. Review the backup, then publish the runtime if other workstations should receive the clean state.",
                reset_result=result,
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            return render_governance(error=f"Employee test-data cleanup failed: {exc}"), 400

    @blueprint.post("/governance/publish")
    @database_publish_required
    def publish_runtime():
        roles = {normalize_role(role) for role in session.get("iam_roles", ())}
        if ROLE_SUPER_OPERATOR in roles and not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
            return "SUPER_OPERATOR cannot publish the runtime database.", 403
        try:
            approved_requests = shared_requests.list_approved() if shared_requests else requests.list_requests()
            reconciled = 0
            skipped: list[str] = []
            for item in approved_requests:
                if item.operation_type in automatic_source_types or item.status != "APPROVED" or employees.change_request_has_history(item.request_id):
                    continue
                try:
                    result = employees.apply_change_request(item.request_id, item.operation_type, item.entity_id, item.payload, str(session["iam_user"]))
                    record_audit(audit_path, str(session["iam_user"]), "REQUEST_APPLIED_LOCALLY", "worker", item.entity_id, new_values={"request_id": item.request_id, "result": result, "reconciled_before_publication": True})
                    reconciled += 1
                except ValueError as exc:
                    skipped.append(f"{item.request_id[:8]} ({exc})")
                    record_audit(audit_path, str(session["iam_user"]), "REQUEST_RECONCILIATION_SKIPPED", "worker", item.entity_id, result="WARNING", new_values={"request_id": item.request_id, "error": str(exc)})
            snapshot = governance.publish(str(session["iam_user"]), request.form.get("expected_checksum", ""))
            active_users = [
                user.username
                for user in users.list_users()
                if user.active and user.status == "ACTIVE"
            ]
            notifications.publish_database_snapshot(
                snapshot.checksum,
                actor=str(session["iam_user"]),
                recipients=active_users,
                reconciled_count=reconciled,
            )
            notice = f"Database published. {reconciled} approved request(s) were applied locally and added to employee history."
            if skipped:
                notice += f" Skipped {len(skipped)} request(s) because the employee is not present locally: {', '.join(skipped)}. Refresh this runtime or resolve those requests before retrying."
            return redirect(url_for("admin.governance_center", notice=notice))
        except Exception as exc:
            return render_governance(error=str(exc)), 400

    @blueprint.post("/governance/restore")
    @master_required
    def restore_runtime():
        if ROLE_SUPER_OPERATOR in {normalize_role(role) for role in session.get("iam_roles", ())}:
            return "SUPER_OPERATOR cannot restore the runtime database.", 403
        try:
            governance.restore(str(session["iam_user"]), request.form.get("backup_name", ""))
            return redirect(url_for("admin.governance_center"))
        except Exception as exc:
            return render_governance(error=str(exc)), 400

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
#endfile
