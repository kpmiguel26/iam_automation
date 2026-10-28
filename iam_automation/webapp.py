"""
File: iam_automation/webapp.py
Purpose: Provides the webapp component of IAM Automation.
Responsibilities: Exposes or coordinates: webapp_pid_path, stop_local_webapp, launch_local_webapp, create_app, start_file_watcher, LocalWebAppServer, ….
Dependencies: errno, multiprocessing, queue, hmac, secrets
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import errno
import json
import logging
import time
import urllib.request
import multiprocessing
import os
import queue
import hmac
import re
import secrets
import signal
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from .identity import CurrentUser, validate_app_user_from_sqlite, windows_username
from .identity_discovery import discovery_path, traceability_path
from .application.session_service import SessionService
from .application.notification_service import NotificationService
from .application.file_watch_service import FileWatchService
from .application.overview_service import OverviewService
from .application.workspace_refresh_service import (
    WorkspaceRefreshService,
    read_published_source_checksum,
    record_published_source_checksum,
)
from .application.publication_state import mark_publication_pending, publication_pending
from .application.user_service import UserService
from .application.governance_service import GovernanceService
from .application.audit_service import record_audit
from .application.temporary_super_operator_service import TemporarySuperOperatorService
from .interfaces.web.admin_routes import create_admin_blueprint
from .interfaces.web.ingestion_configuration_routes import create_ingestion_configuration_blueprint
from .interfaces.web.master_routes import create_master_blueprint
from .interfaces.web.user_routes import create_identity_blueprint, create_user_blueprint
from .interfaces.web.request_routes import create_request_blueprint
from .interfaces.web.bug_report_routes import create_bug_report_blueprint
from .interfaces.web.employee_routes import create_employee_blueprint
from .interfaces.web.report_routes import create_report_blueprint
from .interfaces.web.parallel_engine_app import create_parallel_engine_blueprint
from .interfaces.web.object_routes import create_object_blueprint
from .startup import PreflightResult

try:
    from flask import Flask, redirect, render_template, request, session, url_for
    from waitress import create_server
except ModuleNotFoundError:  # pragma: no cover
    Flask = None  # type: ignore[assignment,misc]
    create_server = None  # type: ignore[assignment]
    redirect = render_template = url_for = None  # type: ignore[assignment]
    request = session = None  # type: ignore[assignment]


def webapp_pid_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".iam_webapp.pid"


def _process_alive(pid: int) -> bool:
    """Check a child PID using the platform-safe process API."""
    if not pid:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return result.returncode == 0 and str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, SystemError):
        return False
    return True


def _terminate_process(pid: int) -> None:
    """Terminate only the recorded webapp process and its descendants."""
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError, SystemError):
        pass


def stop_local_webapp() -> str:
    pid_path = webapp_pid_path()
    try:
        data = json.loads(pid_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "The local webapp was already stopped."
    shutdown_request = Request(
        f"http://127.0.0.1:{int(data['port'])}/__internal/shutdown",
        method="POST",
        headers={"X-IAM-Shutdown-Token": str(data["token"])},
    )
    target_pid = int(data.get("pid", 0))
    try:
        with urlopen(shutdown_request, timeout=3) as response:
            message = response.read().decode("utf-8")
    except OSError:
        # A crashed or externally stopped child can leave the control panel
        # with a stale URL. Remove only the local marker and let the UI restart.
        message = "The local webapp was no longer reachable and was reset."
    # The HTTP response only confirms that shutdown was requested. Wait for
    # the spawned webapp process so Stop/Close cannot leave an orphan behind.
    deadline = time.monotonic() + 5
    while target_pid and time.monotonic() < deadline:
        if not _process_alive(target_pid):
            break
        time.sleep(0.1)
    else:
        if target_pid:
            _terminate_process(target_pid)
            terminate_deadline = time.monotonic() + 2
            while time.monotonic() < terminate_deadline:
                if not _process_alive(target_pid):
                    break
                time.sleep(0.1)
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass
    return message


def launch_local_webapp(preflight_result: PreflightResult, *, open_browser: bool = True) -> "LocalWebAppServer":
    """Launch a server in the current process for direct programmatic use."""
    app = create_app(preflight_result)
    server = LocalWebAppServer(app)
    url = server.start()
    if open_browser:
        webbrowser.open(url)
    return server


def create_app(
    preflight_result: PreflightResult,
    *,
    app_authenticator: Callable[[str, str], CurrentUser] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    shutdown_token: str | None = None,
):
    if Flask is None:
        raise RuntimeError("Flask is required to start the local webapp. Install the UI dependencies first.")
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = secrets.token_urlsafe(32)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    csrf_session_key = "iam_csrf_token"
    http_logger = logging.getLogger("iam.http")
    http_logger.setLevel(logging.INFO)

    def csrf_token() -> str:
        token = session.get(csrf_session_key)
        if not token:
            token = secrets.token_urlsafe(32)
            session[csrf_session_key] = token
        return str(token)

    @app.before_request
    def enforce_csrf():
        token = csrf_token()
        if request.method != "POST" or request.endpoint == "shutdown":
            return None
        submitted = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not submitted or not hmac.compare_digest(str(submitted), token):
            return {"status": "invalid_csrf_token", "message": "The form security token is missing or invalid."}, 400
        return None

    @app.after_request
    def inject_csrf_fields(response):
        if response.mimetype != "text/html":
            return response
        body = response.get_data(as_text=True)
        field = f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'
        pattern = r'(<form\b(?=[^>]*\bmethod\s*=\s*["\']post["\'])[^>]*>)'
        body = re.sub(pattern, rf"\1{field}", body, flags=re.IGNORECASE)
        response.set_data(body)
        return response

    @app.after_request
    def log_http_request(response):
        if request.method in {"GET", "POST"} and not request.path.startswith("/static/") and request.path != "/favicon.ico":
            started_at = request.environ.get("iam_request_started_at")
            duration_ms = ((time.perf_counter() - started_at) * 1000) if isinstance(started_at, float) else 0
            status_label = "OK" if response.status_code < 400 else "WARNING" if response.status_code < 500 else "CRITICAL"
            message = "%s %s | %s %s | %.0f ms | user=%s" % (
                request.method,
                request.path,
                response.status_code,
                status_label,
                duration_ms,
                str(session.get("iam_user") or "anonymous"),
            )
            if response.status_code >= 500:
                http_logger.error(message)
            elif response.status_code >= 400:
                http_logger.warning(message)
            else:
                http_logger.info(message)
        return response

    @app.before_request
    def record_http_start() -> None:
        request.environ["iam_request_started_at"] = time.perf_counter()

    @app.template_filter("human_datetime")
    def human_datetime(value: object) -> str:
        """Render stored UTC timestamps for people while preserving ISO in data."""
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
        hour = parsed.strftime("%I").lstrip("0") or "0"
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}, {hour}:{parsed:%M} {parsed:%p} UTC"

    def finalize_template_value(value: object) -> object:
        """Humanize raw ISO timestamps accidentally rendered without a filter.

        Data exports and technical identifiers are left untouched. Only values
        containing an ISO date-time separator are formatted, so date inputs
        such as ``2026-08-14`` remain valid machine-readable values.
        """
        if isinstance(value, str) and "T" in value:
            formatted = human_datetime(value)
            if formatted != value:
                return formatted
        return value

    app.jinja_env.finalize = finalize_template_value

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        return render_template("errors/500.html"), 500

    static_root = Path(__file__).resolve().parent / "static"
    versioned_assets = (
        static_root / "css" / "app.css",
        static_root / "js" / "business-rule-wizard.js",
        static_root / "js" / "data-tables.js",
        static_root / "js" / "ingestion-identity-guidance.js",
        static_root / "js" / "ingestion-template-library.js",
        static_root / "js" / "object-workspace.js",
    )

    def current_static_version() -> str:
        asset_versions = [f"{path.name}-{path.stat().st_mtime_ns}" for path in versioned_assets if path.is_file()]
        return "-".join(asset_versions) or "dev"

    runtime_path = preflight_result.settings.local_runtime_db_path if preflight_result.settings else None

    def initial_admin_setup_available() -> bool:
        return bool(
            runtime_path
            and runtime_path.is_file()
            and UserService(runtime_path).initial_master_admin_setup_available(windows_username())
        )

    app.extensions["iam_file_watcher"] = None
    app.extensions["parallel_engine_watcher"] = None
    app.extensions["parallel_engine"] = None
    app.extensions["iam_refresh_lock"] = threading.Lock()
    if runtime_path:
        app.register_blueprint(create_admin_blueprint(runtime_path, discovery_file=discovery_path(preflight_result.settings.sharepoint_root_path), sharepoint_root=preflight_result.settings.sharepoint_root_path, local_runtime_path=preflight_result.settings.local_runtime_db_path, published_runtime_path=preflight_result.settings.published_runtime_db_path, audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_ingestion_configuration_blueprint(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path))
        engine_blueprint = create_parallel_engine_blueprint(
            runtime_path,
            preflight_result.settings.sharepoint_root_path,
            dashboard_template="parallel_engine/dashboard_integrated.html",
        )
        app.register_blueprint(engine_blueprint)
        app.extensions.update(engine_blueprint.parallel_engine_extensions)
        app.register_blueprint(create_object_blueprint(runtime_path))
        app.register_blueprint(create_master_blueprint(runtime_path, preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_user_blueprint(runtime_path, audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_identity_blueprint(runtime_path, discovery_file=discovery_path(preflight_result.settings.sharepoint_root_path), traceability_directory=traceability_path(preflight_result.settings.sharepoint_root_path), audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_request_blueprint(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path, audit_path=preflight_result.settings.audit_folder_path))
    app.register_blueprint(create_bug_report_blueprint(runtime_path, preflight_result.settings.sharepoint_root_path))
    app.register_blueprint(create_employee_blueprint(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path if preflight_result.settings else None, audit_path=preflight_result.settings.audit_folder_path if preflight_result.settings else None))
    app.register_blueprint(create_report_blueprint(runtime_path, preflight_result.settings.sharepoint_root_path))

    @app.before_request
    def enforce_session_revocation():
        if runtime_path and runtime_path.is_file() and session.get("iam_user") and session.get("iam_session_started_at"):
            if SessionService(runtime_path).is_revoked(str(session["iam_user"]), str(session["iam_session_started_at"])):
                session.clear()
                return redirect(url_for("login"))
            current = UserService(runtime_path).get_user(str(session["iam_user"]))
            if not current or not current.active or current.status != "ACTIVE":
                session.clear()
                return redirect(url_for("login"))
            roles = TemporarySuperOperatorService(runtime_path).effective_roles(current.username, current.roles)
            session["iam_roles"] = list(roles)
            session["is_admin"] = bool({"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"} & set(roles))

    @app.context_processor
    def shared_template_context():
        roles = tuple(session.get("iam_roles", ()))
        username = str(session.get("iam_user", ""))
        notification_service = NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path) if runtime_path and username and runtime_path.is_file() else None
        unread_count = notification_service.unread_count(username) if notification_service else 0
        unread_notifications = notification_service.list_for_user(username, unread_only=True) if notification_service else []
        recent_notifications = unread_notifications[:5]
        workspace_update_available = False
        if runtime_path and username and runtime_path.is_file() and preflight_result.settings:
            workspace = WorkspaceRefreshService(runtime_path, preflight_result.settings.published_runtime_db_path, preflight_result.settings.sharepoint_root_path)
            workspace_update_available = workspace.version().update_available
        return {
            "csrf_token": csrf_token(),
            "is_admin": bool({"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"} & {str(role).upper() for role in roles}),
            "unread_notification_count": unread_count,
            "recent_notifications": recent_notifications,
            "workspace_update_available": workspace_update_available,
            "static_version": current_static_version(),
            "publication_pending": publication_pending(runtime_path),
        }

    @app.get("/health")
    def health():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        return {"status": "ok"}

    @app.post("/__internal/shutdown")
    def shutdown():
        if not shutdown_token or request.headers.get("X-IAM-Shutdown-Token") != shutdown_token:
            return {"status": "forbidden"}, 403
        if shutdown_callback:
            timer = threading.Timer(0.25, shutdown_callback)
            timer.name = "iam-webapp-shutdown"
            timer.daemon = True
            timer.start()
        return {"status": "stopping"}

    @app.get("/")
    def index():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        return redirect(url_for("dashboard" if session.get("iam_user") else "login"))

    @app.get("/login")
    def login():
        if not preflight_result.ok or not runtime_path:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        if initial_admin_setup_available():
            return redirect(url_for("first_admin_setup"))
        return render_template("auth/login.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), error=None)

    @app.route("/first-run/admin", methods=["GET", "POST"])
    def first_admin_setup():
        if not preflight_result.ok or not runtime_path or not preflight_result.settings:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        username = windows_username()
        service = UserService(runtime_path)
        if not runtime_path.is_file() or not service.initial_master_admin_setup_available(username):
            return redirect(url_for("login"))
        if request.method == "GET":
            return render_template(
                "auth/first_admin.html",
                username=username,
                application_username="",
                display_name="",
                error=None,
                success=None,
                publish_warning=None,
            )

        application_username = str(request.form.get("application_username", "")).strip()
        display_name = str(request.form.get("display_name", "")).strip()
        password = str(request.form.get("password", ""))
        confirmation = str(request.form.get("confirm_password", ""))
        if password != confirmation:
            return render_template("auth/first_admin.html", username=username, application_username=application_username, display_name=display_name, error="The passwords do not match.", success=None, publish_warning=None), 400
        try:
            service.complete_initial_master_admin_setup(username, application_username, display_name, password)
        except ValueError as exc:
            return render_template("auth/first_admin.html", username=username, application_username=application_username, display_name=display_name, error=str(exc), success=None, publish_warning=None), 400

        mark_publication_pending(runtime_path, actor=username, reason="Initial MASTER_ADMIN account setup")
        record_audit(
            preflight_result.settings.audit_folder_path,
            username,
            "INITIAL_MASTER_ADMIN_PASSWORD_SET",
            "app_user",
            application_username,
            computer=preflight_result.current_user.computer if preflight_result.current_user else "local-web",
            new_values={"username": application_username, "display_name": display_name, "roles": ["MASTER_ADMIN"], "status": "ACTIVE"},
        )
        publish_warning = None
        try:
            expected_checksum = read_published_source_checksum(runtime_path)
            snapshot = GovernanceService(
                local_runtime_path=runtime_path,
                published_runtime_path=preflight_result.settings.published_runtime_db_path,
                audit_path=preflight_result.settings.audit_folder_path,
            ).publish(username, expected_checksum=expected_checksum)
            record_published_source_checksum(runtime_path, snapshot.checksum)
        except Exception as exc:
            app.logger.exception("Initial MASTER_ADMIN snapshot publication failed")
            publish_warning = f"The account is ready on this workstation, but the shared snapshot was not updated: {exc}"
        return render_template(
            "auth/first_admin.html",
            username=application_username,
            application_username=application_username,
            display_name=display_name,
            error=None,
            success=f"{display_name} is ready as MASTER_ADMIN. Sign in with the username and password you just created.",
            publish_warning=publish_warning,
        )

    @app.post("/login")
    def sign_in():
        if not preflight_result.ok or not runtime_path:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        if initial_admin_setup_available():
            return redirect(url_for("first_admin_setup"))
        try:
            username = str(request.form.get("username", ""))
            password = str(request.form.get("password", ""))
            user = app_authenticator(username, password) if app_authenticator else validate_app_user_from_sqlite(runtime_path, username, password)
        except PermissionError as exc:
            return render_template("auth/login.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), error=str(exc)), 403
        session.clear()
        session["iam_user"] = user.username
        base_roles = tuple(str(role).strip().upper() for role in getattr(user, "roles", ()))
        normalized_roles = TemporarySuperOperatorService(runtime_path).effective_roles(user.username, base_roles) if runtime_path.is_file() else base_roles
        session["iam_roles"] = list(normalized_roles)
        session["is_admin"] = bool({"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"} & set(normalized_roles))
        from datetime import datetime, timezone
        session["iam_session_started_at"] = datetime.now(timezone.utc).isoformat()
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        username = session.get("iam_user")
        if not username:
            return redirect(url_for("login"))
        workspace = WorkspaceRefreshService(runtime_path, preflight_result.settings.published_runtime_db_path, preflight_result.settings.sharepoint_root_path)
        return render_template("dashboard.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), username=username, roles=tuple(session.get("iam_roles", ())), overview=OverviewService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path).snapshot(str(username)), workspace_message=request.args.get("refreshed"))

    @app.get("/workspace/status")
    def workspace_status():
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return {"status": "unauthorized"}, 401
        workspace = WorkspaceRefreshService(runtime_path, preflight_result.settings.published_runtime_db_path, preflight_result.settings.sharepoint_root_path)
        version = workspace.version()
        return {
            "status": "ok",
            "update_available": version.update_available,
            "published_checksum": version.published_checksum,
            "local_checksum": version.local_checksum,
        }

    @app.post("/workspace/refresh")
    def refresh_workspace():
        username = session.get("iam_user")
        if not username or not runtime_path or not preflight_result.settings:
            return redirect(url_for("login"))
        workspace = WorkspaceRefreshService(runtime_path, preflight_result.settings.published_runtime_db_path, preflight_result.settings.sharepoint_root_path)
        try:
            with app.extensions["iam_refresh_lock"]:
                version, exported = workspace.refresh(str(username))
            current = next((user for user in UserService(runtime_path).list_users() if user.username.lower() == str(username).lower()), None)
            if current:
                session["iam_roles"] = list(current.roles)
                session["is_admin"] = bool({"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"} & set(current.roles))
            return redirect(url_for("dashboard", refreshed=f"Workspace refreshed successfully. {exported} pending request(s) preserved."))
        except Exception as exc:
            return render_template("dashboard.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), username=str(username), roles=tuple(session.get("iam_roles", ())), overview=OverviewService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path).snapshot(str(username)), workspace_version=workspace.version(), workspace_error=str(exc)), 409

    @app.get("/profile")
    def profile():
        if not session.get("iam_user"):
            return redirect(url_for("login"))
        return render_template("profile.html", username=str(session["iam_user"]), roles=tuple(session.get("iam_roles", ())), sharepoint_path=str(preflight_result.settings.sharepoint_root_path))

    @app.get("/help/testing")
    def testing_help():
        if not session.get("iam_user"):
            return redirect(url_for("login"))
        return render_template("help/testing.html")

    @app.get("/help/employees")
    def employees_help():
        if not session.get("iam_user"):
            return redirect(url_for("login"))
        return render_template("help/employees.html")

    @app.get("/help/business-rules")
    def business_rules_help():
        if not session.get("iam_user"):
            return redirect(url_for("login"))
        return render_template("help/business_rules.html")

    @app.get("/notifications")
    def notifications_page():
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        service = NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path)
        service.expire(str(username))
        status = request.args.get("status", "ALL").upper()
        severity = request.args.get("severity", "ALL").upper()
        if status not in {"ALL", "UNREAD", "READ", "RESOLVED", "EXPIRED"}:
            status = "ALL"
        if severity not in {"ALL", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            severity = "ALL"
        items = service.list_for_user(str(username))
        if status != "ALL":
            items = [item for item in items if item.status == status]
        if severity != "ALL":
            items = [item for item in items if item.severity == severity]
        return render_template(
            "notifications.html",
            notifications=items,
            filters={"status": status, "severity": severity},
            unread_count=service.unread_count(str(username)),
        )

    @app.get("/notifications/<notification_id>/open")
    def notification_open(notification_id: str):
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        service = NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path)
        item = next((candidate for candidate in service.list_for_user(str(username)) if candidate.notification_id == notification_id), None)
        if item is None:
            return redirect(url_for("notifications_page", notice="Notification was not found.", notice_type="warning"))
        service.mark_read(str(username), notification_id)
        return redirect(item.target_route or url_for("notifications_page"))

    @app.post("/notifications/<notification_id>/read")
    def notification_read(notification_id: str):
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path).mark_read(str(username), notification_id)
        return redirect(url_for("notifications_page", status=request.form.get("status", "ALL"), severity=request.form.get("severity", "ALL"), notice="Notification marked as read.", notice_type="success"))

    @app.post("/notifications/<notification_id>/resolve")
    def notification_resolve(notification_id: str):
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path).resolve(str(username), notification_id)
        return redirect(url_for("notifications_page", status=request.form.get("status", "ALL"), severity=request.form.get("severity", "ALL"), notice="Notification resolved.", notice_type="success"))

    @app.post("/notifications/read-all")
    def notification_read_all():
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        count = NotificationService(runtime_path, sharepoint_root=preflight_result.settings.sharepoint_root_path).mark_all_read(str(username))
        return redirect(url_for("notifications_page", status=request.form.get("status", "ALL"), severity=request.form.get("severity", "ALL"), notice=f"{count} notification(s) marked as read.", notice_type="success"))

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


def start_file_watcher(preflight_result: PreflightResult):
    if not preflight_result.settings:
        return None
    database_path = preflight_result.settings.local_runtime_db_path
    watcher = FileWatchService(database_path, preflight_result.settings.sharepoint_root_path).start(interval_seconds=120.0)
    return watcher


@dataclass
class LocalWebAppServer:
    app: object
    host: str = "127.0.0.1"
    port: int = 0
    _server: object | None = None
    _thread: threading.Thread | None = None

    def _run(self) -> None:
        try:
            self._server.run()  # type: ignore[union-attr]
        except OSError as exc:
            if exc.errno != errno.EBADF and getattr(exc, "winerror", None) != 10038:
                raise

    def start(self) -> str:
        if create_server is None:
            raise RuntimeError("Flask and Waitress are required to start the local webapp.")
        # Waitress emits a warning when static assets briefly queue during page load.
        # Keep real request/server errors visible while avoiding normal startup noise.
        logging.getLogger("waitress.queue").setLevel(logging.ERROR)
        self._server = create_server(self.app, host=self.host, port=self.port, threads=4)
        self.port = int(self._server.effective_port)  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._run, name="iam-local-webapp", daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}/login"

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        if server is None:
            return
        # Waitress request workers call ``server.pull_trigger()`` after each
        # request.  Closing the trigger first can race with that final call
        # and produce a misleading ``EBADF`` traceback during normal shutdown.
        # Drain the workers before closing the trigger so no request worker can
        # touch it after it has been closed.
        task_dispatcher = getattr(server, "task_dispatcher", None)
        if task_dispatcher is not None:
            task_dispatcher.shutdown(timeout=2)
        server.close()  # type: ignore[attr-defined]
        if thread is not None:
            thread.join(timeout=2)
        self._server = None
        self._thread = None


def _serve_webapp_process(preflight_result: PreflightResult, ready_queue, log_queue) -> None:
    """Serve the local app in a separate process from the Qt control panel."""
    shutdown_token = secrets.token_urlsafe(32)
    class QueueLogHandler(logging.Handler):
        def emit(self, record) -> None:
            try:
                log_queue.put_nowait(self.format(record))
            except Exception:
                pass
    log_handler = QueueLogHandler()
    log_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logging.getLogger().addHandler(log_handler)
    logging.getLogger("waitress").setLevel(logging.ERROR)
    server_holder: dict[str, LocalWebAppServer] = {}

    def shutdown_server() -> None:
        server = server_holder.get("server")
        if server:
            server.stop()

    app = create_app(preflight_result, shutdown_callback=shutdown_server, shutdown_token=shutdown_token)
    # DEPRECATED: keep the legacy watcher implementation for compatibility,
    # but leave it stopped while the parallel engine watcher owns discovery.
    # watcher = start_file_watcher(preflight_result)
    # app.extensions["iam_file_watcher"] = watcher
    watcher = None
    parallel_watcher = app.extensions.get("parallel_engine_watcher")
    server = LocalWebAppServer(app)
    server_holder["server"] = server
    url = server.start()
    webapp_pid_path().write_text(json.dumps({"pid": os.getpid(), "port": server.port, "token": shutdown_token}) + "\n", encoding="utf-8")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                break
        except Exception:
            time.sleep(.1)
    else:
        raise RuntimeError("Waitress did not become ready within the expected time.")
    ready_queue.put(url)
    try:
        if parallel_watcher is not None:
            parallel_watcher.start()
        if server._thread:
            # Keep the child alive while Waitress serves requests. The control
            # panel stops it through the internal shutdown endpoint; SIGINT is
            # handled below for terminal-based shutdown.
            try:
                server._thread.join()
            except KeyboardInterrupt:
                # SIGINT is delivered to the process group on macOS/Windows.
                # Cleanup below closes Waitress and stops the watcher.
                pass
    finally:
        if watcher:
            watcher.stop()
        if parallel_watcher:
            parallel_watcher.stop()
        server.stop()
        try:
            webapp_pid_path().unlink()
        except FileNotFoundError:
            pass
        logging.getLogger().removeHandler(log_handler)


def launch_local_webapp_process(
    preflight_result: PreflightResult,
    *,
    open_browser: bool = True,
    startup_timeout: float = 10.0,
) -> tuple[multiprocessing.Process, str, object]:
    """Start Flask independently so the Qt launcher remains responsive."""
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    log_queue = context.Queue()
    process = context.Process(target=_serve_webapp_process, args=(preflight_result, ready_queue, log_queue), name="iam-flask-webapp", daemon=False)
    process.start()
    try:
        url = ready_queue.get(timeout=startup_timeout)
    except queue.Empty as exc:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        raise RuntimeError("The local Flask webapp did not start within the expected time.") from exc
    if open_browser:
        webbrowser.open(url)
    return process, url, log_queue


def open_browser(url: str) -> None:
    webbrowser.open(url, new=2)
#endfile
