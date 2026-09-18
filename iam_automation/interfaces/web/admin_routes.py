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
import logging
import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template, request, send_file, session, url_for

from ...application.delegation_service import DelegationService
from ...application.employee_service import EmployeeService
from ...application.employee_reset_service import EmployeeResetService
from ...application.legacy_star_migration_service import LegacyStarMigrationService
from ...application.audit_service import record_audit
from ...application.import_service import ImportService
from ...application.notification_service import NotificationService
from ...application.business_rule_service import BusinessRuleService
from ...application.condition_evaluator import ConditionEvaluator
from ...application.rule_configuration_service import RuleConfigurationService
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
    logger = logging.getLogger(__name__)
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
    rule_configuration = RuleConfigurationService(database_path)
    users = UserService(database_path)
    employees = EmployeeService(database_path)
    employee_reset = EmployeeResetService(
        local_runtime_path or database_path,
        audit_path=audit_path or database_path.parent / "audit",
        backup_directory=(published_runtime_path or database_path).parent / "backups",
    )
    legacy_star_migration = LegacyStarMigrationService(local_runtime_path or database_path, backup_directory=(published_runtime_path or database_path).parent / "backups")
    salesforce = SalesforceExportService(database_path, audit_path=audit_path)
    automatic_source_types = {"ROSTER_LOCK", "MASTER_ROSTER", "RSR_SUPPLIER_WORKER_DETAILS", "ACCESSNOW"}

    def migration_health() -> dict[str, object]:
        """Return read-only checks for the current schema and compact pilot."""
        expected = "0014_worker_field_history"
        result: dict[str, object] = {
            "expected_revision": expected,
            "revision": current_database_revision(local_runtime_path or database_path),
            "revision_ok": False,
            "tables": [],
            "columns": {},
            "indexes": [],
            "field_count": 0,
            "value_count": 0,
            "error": None,
        }
        path = (local_runtime_path or database_path).expanduser().resolve()
        try:
            connection = sqlite3.connect(str(path))
            connection.execute("PRAGMA query_only = ON")
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            expected_tables = (
                "dim_source", "dim_field", "dim_date", "dim_vendor",
                "fact_source_snapshot", "fact_worker_field", "fact_termination", "fact_assignment",
                "fact_worker_field_history",
            )
            result["tables"] = [{"name": name, "present": name in table_names} for name in expected_tables]
            for table_name in expected_tables:
                if table_name in table_names:
                    result["columns"][table_name] = [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]
            result["indexes"] = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_star_%'")]
            if "dim_field" in table_names:
                result["field_count"] = connection.execute("SELECT COUNT(*) FROM dim_field WHERE active = 1").fetchone()[0]
            if "fact_worker_field" in table_names:
                result["value_count"] = connection.execute("SELECT COUNT(*) FROM fact_worker_field").fetchone()[0]
            result["revision_ok"] = result["revision"] == expected and all(item["present"] for item in result["tables"])
        except sqlite3.Error as exc:
            result["error"] = str(exc)
        finally:
            if "connection" in locals():
                connection.close()
        return result

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
            migration_health=migration_health(),
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
        return redirect(url_for("admin.quarantine", status=status, severity=severity, notice=request.args.get("notice")))

    @blueprint.get("/quarantine")
    @admin_required
    def quarantine():
        status = request.args.get("status", "OPEN").upper()
        severity = request.args.get("severity", "ALL").upper()
        rule_id = request.args.get("rule_id", "ALL").strip() or "ALL"
        findings = rules.list_quarantine_findings(status=status, severity=severity, rule_id=rule_id)
        configured_rules = rules.list_rules()
        rule_cards = {}
        for configured in configured_rules:
            configured_rule_id = configured["rule"].rule_id
            if rule_id != "ALL" and rule_id != configured_rule_id:
                continue
            rule_cards[configured_rule_id] = {
                "rule_id": configured_rule_id,
                "rule_name": configured["rule"].name,
                "rule_description": configured["rule"].description or "Advisory check for imported employee data.",
                "source_system": configured["source_system"],
                "finding_count": 0,
                "statuses": set(),
                "severities": set(),
            }
        for item in findings:
            key = item["finding"].rule_id
            card = rule_cards.setdefault(key, {
                "rule_id": key,
                "rule_name": item["rule_name"],
                "rule_description": item["rule_description"],
                "source_system": item["source_system"],
                "finding_count": 0,
                "statuses": set(),
                "severities": set(),
            })
            card["finding_count"] += 1
            card["statuses"].add(item["finding"].status)
            card["severities"].add(item["finding"].severity)
        context = {
            "findings": findings,
            "rule_cards": list(rule_cards.values()),
            "quarantine": imports.list_quarantine(open_only=True),
            "rules": configured_rules,
            "status": status,
            "severity": severity,
            "rule_id": rule_id,
            "severities": BusinessRuleService.ALLOWED_SEVERITIES,
            "message": request.args.get("notice"),
            "error": None,
        }
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_quarantine_findings_panel.html", **context)
        return render_template("admin/quarantine.html", **context)

    @blueprint.get("/quarantine/rules/<rule_id>")
    @admin_required
    def quarantine_rule_detail(rule_id: str):
        status = request.args.get("status", "OPEN").upper()
        severity = request.args.get("severity", "ALL").upper()
        item = next((value for value in rules.list_rules() if value["rule"].rule_id == rule_id), None)
        if item is None:
            return redirect(url_for("admin.quarantine", notice="Rule not found."))
        return render_template(
            "admin/quarantine_rule_detail.html",
            rule=item,
            findings=rules.list_quarantine_findings(status=status, severity=severity, rule_id=rule_id),
            status=status,
            severity=severity,
            severities=BusinessRuleService.ALLOWED_SEVERITIES,
        )

    @blueprint.post("/quarantine/findings/<finding_id>/status")
    @blueprint.post("/business-rule-findings/<finding_id>/status")
    @admin_required
    def business_rule_finding_status(finding_id: str):
        try:
            status = request.form.get("status", "").upper()
            note = request.form.get("note", "")
            rules.update_finding(finding_id, status=status, actor=str(session["iam_user"]), note=note)
            record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_FINDING_STATUS_CHANGED", "rule_finding", finding_id, new_values={"status": status, "note": note})
            if request.headers.get("HX-Request") == "true":
                item = next((item for item in rules.list_quarantine_findings(status="ALL") if item["finding"].finding_id == finding_id), None)
                if request.form.get("view") == "table":
                    return render_template("admin/_quarantine_finding_table_row.html", item=item) if item is not None else ""
                return render_template("admin/_quarantine_finding_row.html", item=item) if item is not None else ""
            return redirect(url_for("admin.quarantine", notice="Finding updated."))
        except ValueError as exc:
            return redirect(url_for("admin.quarantine", notice=str(exc)))

    @blueprint.route("/business-rules", methods=["GET", "POST"])
    @admin_required
    def business_rules():
        error = None
        message = None
        if request.method == "POST":
            try:
                condition_json = request.form.get("condition_json", "").strip()
                if condition_json:
                    rule_id = rules.create_complex_rule(name=request.form.get("name", ""), description=request.form.get("description", ""), condition=json.loads(condition_json), severity=request.form.get("severity", "WARNING"), phase=request.form.get("phase", "AFTER"), source_system=request.form.get("source_system", "ALL"), actor=str(session["iam_user"]))
                else:
                    rule_id = rules.create_rule(name=request.form.get("name", ""), description=request.form.get("description", ""), field=request.form.get("field", ""), operator=request.form.get("operator", ""), value=request.form.get("value", ""), severity=request.form.get("severity", "WARNING"), phase=request.form.get("phase", "AFTER"), source_system=request.form.get("source_system", "ALL"), actor=str(session["iam_user"]))
                mark_publication_pending(database_path, actor=str(session["iam_user"]), reason="Business rule created")
                record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_CREATED", "business_rule", rule_id, new_values={"name": request.form.get("name", ""), "source_system": request.form.get("source_system", "ALL"), "field": request.form.get("field", ""), "operator": request.form.get("operator", ""), "severity": request.form.get("severity", "WARNING"), "phase": request.form.get("phase", "AFTER")})
                message = "Rule created as DRAFT. Activate it after reviewing the condition."
            except ValueError as exc:
                error = str(exc)
        if request.headers.get("HX-Request") == "true":
            if error:
                return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=message, error=error), 400
            return render_template("admin/_business_rule_create_response.html", rules=rules.list_rules(), message=message, error=error)
        return render_template("admin/business_rules.html", rules=rules.list_rules(), operators=BusinessRuleService.ALLOWED_OPERATORS, severities=BusinessRuleService.ALLOWED_SEVERITIES, phases=BusinessRuleService.ALLOWED_PHASES, fields=rules.available_fields(), message=message or request.args.get("notice"), error=error)

    @blueprint.post("/business-rules/<rule_id>/test")
    @admin_required
    def business_rule_test(rule_id: str):
        """Preview a draft or active rule against persisted local evidence."""
        configured_rules = rules.list_rules()
        try:
            result = rules.test_rule(rule_id, batch_id=request.form.get("batch_id", ""))
            message = f"Rule test completed: {result['match_count']} match(es) across {result['evaluated']} evaluated record(s)."
            error = None
        except ValueError as exc:
            result = None
            message = None
            error = str(exc)
        context = {
            "rules": configured_rules,
            "operators": BusinessRuleService.ALLOWED_OPERATORS,
            "severities": BusinessRuleService.ALLOWED_SEVERITIES,
            "phases": BusinessRuleService.ALLOWED_PHASES,
            "fields": rules.available_fields(),
            "message": message,
            "error": error,
            "test_result": result,
        }
        if request.headers.get("HX-Request") == "true":
            return render_template("admin/_business_rule_results.html", **context), 400 if error else 200
        if error:
            return render_template("admin/business_rules.html", **context), 400
        return render_template("admin/business_rules.html", **context)

    @blueprint.route("/business-rules/config", methods=["GET", "POST"])
    @admin_required
    def business_rule_configuration():
        message = request.args.get("notice")
        error = None
        if request.method == "POST":
            actor = str(session["iam_user"])
            section = request.form.get("section", "").strip().lower()
            try:
                if section == "context":
                    result = rule_configuration.save_context(
                        calendar_id=request.form.get("calendar_id", "").strip(),
                        timezone_name=request.form.get("timezone", ""),
                        missing_data_behavior=request.form.get("missing_data_behavior", ""),
                        date_boundary=request.form.get("date_boundary", ""),
                        actor=actor,
                    )
                    record_audit(audit_path, actor, "RULE_CONTEXT_UPDATED", "rule_context", "context:default", new_values=result)
                    mark_publication_pending(database_path, actor=actor, reason="Business rule context updated")
                    message = f"Rule context saved as version {result['version']}."
                elif section == "calendar":
                    holiday_rows = []
                    enabled_holidays = set(request.form.getlist("holiday_enabled"))
                    holiday_dates = request.form.getlist("holiday_date")
                    holiday_labels = request.form.getlist("holiday_label")
                    holiday_sources = request.form.getlist("holiday_source")
                    holiday_countries = request.form.getlist("holiday_country")
                    holiday_years = request.form.getlist("holiday_year")
                    holiday_types = request.form.getlist("holiday_type")
                    holiday_observed_dates = request.form.getlist("holiday_observed_date")
                    for index, holiday_date in enumerate(holiday_dates):
                        holiday_rows.append({
                            "date": holiday_date,
                            "label": holiday_labels[index] if index < len(holiday_labels) else "",
                            "source": holiday_sources[index] if index < len(holiday_sources) else "MANUAL",
                            "country": holiday_countries[index] if index < len(holiday_countries) else "",
                            "year": holiday_years[index] if index < len(holiday_years) and holiday_years[index] else None,
                            "type": holiday_types[index] if index < len(holiday_types) else "",
                            "observed_date": holiday_observed_dates[index] if index < len(holiday_observed_dates) else holiday_date,
                            "enabled": str(index) in enabled_holidays,
                        })
                    result = rule_configuration.save_calendar(
                        calendar_id=request.form.get("calendar_id", "").strip(),
                        label=request.form.get("label", ""),
                        timezone_name=request.form.get("timezone", ""),
                        weekdays=request.form.getlist("weekdays"),
                        holidays=request.form.get("holidays", ""),
                        actor=actor,
                        holiday_rows=holiday_rows,
                    )
                    record_audit(audit_path, actor, "RULE_CALENDAR_UPDATED", "rule_calendar", result["calendar_id"], new_values=result)
                    mark_publication_pending(database_path, actor=actor, reason="Business rule calendar updated")
                    message = f"Calendar saved as version {result['version']}."
                elif section == "field":
                    result = rule_configuration.update_field(
                        field_id=request.form.get("field_id", "").strip(),
                        data_type=request.form.get("data_type", "TEXT"),
                        nullable=request.form.get("nullable") == "on",
                        rule_enabled=request.form.get("rule_enabled") == "on",
                        normalization_name=request.form.get("normalization_name", "identity"),
                        actor=actor,
                    )
                    record_audit(audit_path, actor, "RULE_FIELD_METADATA_UPDATED", "dim_field", result["field_key"], new_values=result)
                    mark_publication_pending(database_path, actor=actor, reason="Business rule field metadata updated")
                    message = f"Field metadata saved as version {result['version']}."
                else:
                    raise ValueError("Choose a rule configuration section to save.")
            except ValueError as exc:
                error = str(exc)
        return render_template("admin/business_rule_configuration.html", **rule_configuration.configuration(), current_year=datetime.now(timezone.utc).year, message=message, error=error)

    @blueprint.post("/business-rules/config/holidays/import")
    @admin_required
    def business_rule_holiday_import():
        actor = str(session["iam_user"])
        try:
            result = rule_configuration.import_holidays(
                calendar_id=request.form.get("calendar_id", "").strip(),
                country_code=request.form.get("country_code", ""),
                year=request.form.get("year", ""),
                actor=actor,
            )
            record_audit(audit_path, actor, "RULE_HOLIDAYS_IMPORTED", "rule_calendar", result["calendar_id"], new_values=result)
            mark_publication_pending(database_path, actor=actor, reason="Public holidays imported for business rules")
            message = f"Imported {result['imported']} public holiday(s); {result['added']} new row(s) added. Review the switches and save the calendar."
            return render_template("admin/business_rule_configuration.html", **rule_configuration.configuration(), current_year=datetime.now(timezone.utc).year, message=message, error=None)
        except ValueError as exc:
            return render_template("admin/business_rule_configuration.html", **rule_configuration.configuration(), current_year=datetime.now(timezone.utc).year, message=None, error=str(exc)), 400

    @blueprint.get("/business-rules/wizard/phase")
    @admin_required
    def business_rule_wizard_phase():
        return render_template("admin/_business_rule_wizard_state.html", step=1, phases=BusinessRuleService.ALLOWED_PHASES, phase=request.args.get("phase", "").upper())

    @blueprint.get("/business-rules/wizard/start")
    @admin_required
    def business_rule_wizard_start():
        return render_template("admin/_business_rule_wizard.html")

    @blueprint.route("/business-rules/wizard/source", methods=["GET", "POST"])
    @admin_required
    def business_rule_wizard_source():
        values = request.form if request.method == "POST" else request.args
        phase = values.get("phase", "").upper()
        if phase not in BusinessRuleService.ALLOWED_PHASES:
            return render_template("admin/_business_rule_wizard_state.html", step=1, phases=BusinessRuleService.ALLOWED_PHASES, phase="", error="Choose when the rule should run."), 400
        return render_template("admin/_business_rule_wizard_state.html", step=2, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system="", source_label="", sources=rules.available_sources())

    @blueprint.route("/business-rules/wizard/details", methods=["GET", "POST"])
    @admin_required
    def business_rule_wizard_details():
        values = request.form if request.method == "POST" else request.args
        phase = values.get("phase", "").upper()
        source_system = values.get("source_system", "").upper()
        valid_sources = {source["key"] for source in rules.available_sources()}
        if phase not in BusinessRuleService.ALLOWED_PHASES:
            return render_template("admin/_business_rule_wizard_state.html", step=1, phases=BusinessRuleService.ALLOWED_PHASES, phase="", error="Choose when the rule should run."), 400
        if source_system not in valid_sources:
            return render_template("admin/_business_rule_wizard_state.html", step=2, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system="", source_label="", sources=rules.available_sources(), error="Choose the report that owns this rule."), 400
        source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
        return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), field_options=rules.available_field_options(source_system), operator_options=BusinessRuleService.operator_options(), condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)))

    @blueprint.route("/business-rules/wizard/condition", methods=["GET", "POST"])
    @admin_required
    def business_rule_wizard_condition():
        values = request.form if request.method == "POST" else request.args
        phase = values.get("phase", "").upper()
        source_system = values.get("source_system", "").upper()
        valid_sources = {source["key"] for source in rules.available_sources()}
        if phase not in BusinessRuleService.ALLOWED_PHASES:
            return render_template("admin/_business_rule_wizard_state.html", step=1, phases=BusinessRuleService.ALLOWED_PHASES, phase="", error="Choose when the rule should run."), 400
        if source_system not in valid_sources:
            return render_template("admin/_business_rule_wizard_state.html", step=2, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system="", source_label="", sources=rules.available_sources(), error="Choose the report that owns this rule."), 400
        source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
        condition_mode = values.get("condition_mode", "simple").strip().lower()
        condition_json = values.get("condition_json", "").strip()
        if request.method == "GET" and condition_mode == "explicit" and condition_json:
            try:
                condition = json.loads(condition_json)
                ConditionEvaluator().validate(condition)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode="explicit", condition_json=condition_json, condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)), error=str(exc)), 400
            return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode="explicit", condition_json=condition_json, condition_display=BusinessRuleService._condition_display(condition), condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)))
        if condition_mode == "explicit" or values.getlist("condition_operator"):
            try:
                condition = rules.condition_from_form(values)
                ConditionEvaluator().validate(condition)
            except (ValueError, TypeError, IndexError, json.JSONDecodeError) as exc:
                return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode="explicit", condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)), error=str(exc)), 400
            return render_template("admin/_business_rule_wizard_state.html", step=4, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode="explicit", condition_json=json.dumps(condition, sort_keys=True), condition_display=BusinessRuleService._condition_display(condition), field="condition", field_label="Explicit condition", operator="composite", value="",)
        field = values.get("field", "").strip()
        operator = values.get("operator", "").strip()
        value = values.get("value", "").strip()
        if field not in set(rules.available_fields(source_system)) or operator not in BusinessRuleService.ALLOWED_OPERATORS or (operator in {"equals", "not_equals", "contains", "in"} and not value):
            return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), field=field, operator=operator, value=value, field_options=rules.available_field_options(source_system), operator_options=BusinessRuleService.operator_options(), condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)), error="Choose a valid field and check type. Add a value when the selected check requires one."), 400
        return render_template("admin/_business_rule_wizard_state.html", step=4, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), field=field, field_label=BusinessRuleService._humanize_field(field), operator=operator, value=value)

    @blueprint.route("/business-rules/wizard/review", methods=["GET", "POST"])
    @admin_required
    def business_rule_wizard_review():
        if request.method == "GET":
            values = request.args
            phase = values.get("phase", "").upper()
            source_system = values.get("source_system", "").upper()
            field = values.get("field", "").strip()
            operator = values.get("operator", "").strip()
            value = values.get("value", "").strip()
            condition_mode = values.get("condition_mode", "simple").strip().lower()
            condition_json = values.get("condition_json", "").strip()
            source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
            return render_template("admin/_business_rule_wizard_state.html", step=4, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode=condition_mode, condition_json=condition_json, condition_display=values.get("condition_display", ""), field=field, field_label=BusinessRuleService._humanize_field(field), operator=operator, value=value, rule_number=values.get("rule_number", ""), name=values.get("name", ""), description=values.get("description", ""), generated_name=values.get("generated_name", ""))
        phase = request.form.get("phase", "").upper()
        source_system = request.form.get("source_system", "").upper()
        operator = request.form.get("operator", "").strip()
        field = request.form.get("field", "").strip()
        value = request.form.get("value", "").strip()
        condition_mode = request.form.get("condition_mode", "simple").strip().lower()
        condition_json = request.form.get("condition_json", "").strip()
        condition_display = request.form.get("condition_display", "").strip()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "")
        rule_number = request.form.get("rule_number", "").strip()
        generated_name = request.form.get("generated_name", "").strip()
        valid_sources = {source["key"] for source in rules.available_sources()}
        source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
        if condition_mode == "explicit":
            try:
                if not condition_json:
                    raise ValueError("The comparison was not saved. Return to step 3 and complete the calculated value before continuing.")
                condition = json.loads(condition_json)
                ConditionEvaluator().validate(condition)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label if source_system in valid_sources else source_system, sources=rules.available_sources(), condition_mode="explicit", condition_json=condition_json, condition_display=condition_display, field="condition", field_label="Explicit condition", operator="composite", value="", condition_field_options=rules.available_condition_fields(), explicit_operators=tuple(sorted(ConditionEvaluator.OPERATORS)), condition_functions=tuple(sorted(ConditionEvaluator.DERIVED_FUNCTIONS)), error=str(exc)), 200 if request.headers.get("HX-Request") == "true" else 400
        elif phase not in BusinessRuleService.ALLOWED_PHASES or source_system not in valid_sources or operator not in BusinessRuleService.ALLOWED_OPERATORS or not field or (operator in {"equals", "not_equals", "contains", "in"} and not value):
            source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
            return render_template("admin/_business_rule_wizard_state.html", step=3, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), field=field, operator=operator, value=value, field_options=rules.available_field_options(source_system), operator_options=BusinessRuleService.operator_options(), error="Choose a field and a check type. Add a value when the selected check requires one."), 200 if request.headers.get("HX-Request") == "true" else 400
        source_label = next((source["label"] for source in rules.available_sources() if source["key"] == source_system), source_system)
        if not generated_name or not name or not rule_number:
            return render_template("admin/_business_rule_wizard_state.html", step=4, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode=condition_mode, condition_json=condition_json, condition_display=condition_display, field=field, operator=operator, value=value, rule_number=rule_number, name=name, description=description, generated_name=generated_name, error="Complete the rule number and descriptive name so the frontend can compose the final name."), 200 if request.headers.get("HX-Request") == "true" else 400
        return render_template("admin/_business_rule_wizard_state.html", step=5, phases=BusinessRuleService.ALLOWED_PHASES, phase=phase, source_system=source_system, source_label=source_label, sources=rules.available_sources(), condition_mode=condition_mode, condition_json=condition_json, condition_display=condition_display, name=name, description=description, generated_name=generated_name, rule_number=rule_number, field=field, field_label=BusinessRuleService._humanize_field(field), operator=operator, value=value, severities=BusinessRuleService.ALLOWED_SEVERITIES, severity=request.form.get("severity", "WARNING"))

    @blueprint.post("/business-rules/<rule_id>/status")
    @admin_required
    def business_rule_status(rule_id: str):
        try:
            status = request.form.get("status", "").upper()
            rules.set_status(rule_id, status)
            mark_publication_pending(database_path, actor=str(session["iam_user"]), reason=f"Business rule status changed: {status}")
            finding_count = rules.evaluate_all_batches() if status == "ACTIVE" else 0
            record_audit(audit_path, str(session["iam_user"]), "BUSINESS_RULE_STATUS_CHANGED", "business_rule", rule_id, new_values={"status": status})
            notice = f"Rule enabled. We checked previous imports and found {finding_count} new review item(s)." if status == "ACTIVE" else "Rule disabled. Existing review items were preserved."
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=notice, error=None)
            return redirect(url_for("admin.business_rules", notice=notice))
        except ValueError as exc:
            return render_template("admin/business_rules.html", rules=rules.list_rules(), operators=BusinessRuleService.ALLOWED_OPERATORS, severities=BusinessRuleService.ALLOWED_SEVERITIES, message=None, error=str(exc)), 400

    @blueprint.post("/business-rules/<rule_id>/delete")
    @admin_required
    def business_rule_delete(rule_id: str):
        try:
            deleted = rules.delete_rule(rule_id)
            mark_publication_pending(database_path, actor=str(session["iam_user"]), reason="Business rule deleted")
            record_audit(
                audit_path,
                str(session["iam_user"]),
                "BUSINESS_RULE_DELETED",
                "business_rule",
                rule_id,
                new_values=deleted,
            )
            notice = (
                f"Rule deleted. Removed {deleted['versions']} version(s), "
                f"{deleted['findings']} finding(s) and "
                f"{deleted['quarantine_facts']} quarantine detection(s)."
            )
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=notice, error=None)
            return redirect(url_for("admin.business_rules", notice=notice))
        except ValueError as exc:
            if request.headers.get("HX-Request") == "true":
                return render_template("admin/_business_rule_results.html", rules=rules.list_rules(), message=None, error=str(exc)), 400
            return redirect(url_for("admin.business_rules", notice=str(exc)))

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
                    try:
                        finding_count = rules.evaluate_batch(batch.batch_id)
                    except Exception:
                        logger.exception("Business rule evaluation failed after import %s", batch.batch_id)
                        finding_count = 0
                        error = "Import completed, but rule evaluation failed. Review the startup log and retry evaluation later."
                    message = f"Import {batch.batch_id[:8]} processed: {batch.valid_rows} valid, {batch.quarantine_rows} quarantined. {finding_count} rule finding(s) created."
                except (ValueError, RuntimeError) as exc:
                    error = str(exc)
                except Exception:
                    logger.exception("Import failed safely for %s", upload.filename)
                    error = "The import failed safely. The next import can be attempted; review the startup log for details."
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

    @blueprint.post("/governance/rebuild-star-testing-runtime")
    @database_publish_required
    def rebuild_star_testing_runtime():
        if request.form.get("confirmation", "").strip() != "REBUILD STAR TESTING RUNTIME":
            return render_governance(error="Type REBUILD STAR TESTING RUNTIME exactly to confirm this testing reset."), 400
        try:
            result = employee_reset.reset(str(session["iam_user"]), clear_workflow_records=True, clear_business_rules=True)
            return render_governance(
                message="Testing runtime rebuilt for the star schema. Rules, detections and employee/import data were cleared locally; users, roles, settings and audit evidence were preserved.",
                reset_result=result,
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            return render_governance(error=f"Star-schema testing reset failed: {exc}"), 400

    @blueprint.post("/governance/migrate-legacy-star")
    @database_publish_required
    def migrate_legacy_star():
        if request.form.get("confirmation", "").strip() != "MIGRATE LEGACY TO STAR":
            return render_governance(error="Type MIGRATE LEGACY TO STAR exactly to confirm this migration."), 400
        try:
            result = legacy_star_migration.migrate(str(session["iam_user"]))
            return render_governance(message=f"Legacy snapshots migrated: {result['history_fields_written']} history fields and {result['current_fields_written']} current fields. Backup created at {result['backup']}.")
        except (OSError, sqlite3.Error, ValueError) as exc:
            return render_governance(error=f"Legacy star migration failed: {exc}"), 400

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
