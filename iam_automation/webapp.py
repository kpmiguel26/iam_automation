from __future__ import annotations

import errno
import json
import multiprocessing
import os
import queue
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from .identity import CurrentUser, validate_app_user_from_sqlite
from .identity_discovery import discovery_path
from .application.session_service import SessionService
from .application.notification_service import NotificationService
from .application.file_watch_service import FileWatchService
from .application.overview_service import OverviewService
from .application.workspace_refresh_service import WorkspaceRefreshService
from .application.user_service import UserService
from .application.temporary_super_operator_service import TemporarySuperOperatorService
from .interfaces.web.admin_routes import create_admin_blueprint
from .interfaces.web.master_routes import create_master_blueprint
from .interfaces.web.user_routes import create_identity_blueprint, create_user_blueprint
from .interfaces.web.request_routes import create_request_blueprint
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


def stop_local_webapp() -> str:
    data = json.loads(webapp_pid_path().read_text(encoding="utf-8"))
    shutdown_request = Request(
        f"http://127.0.0.1:{int(data['port'])}/__internal/shutdown",
        method="POST",
        headers={"X-IAM-Shutdown-Token": str(data["token"])},
    )
    with urlopen(shutdown_request, timeout=3) as response:
        return response.read().decode("utf-8")


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
    css_path = Path(__file__).resolve().parent / "static" / "css" / "app.css"
    static_version = str(int(css_path.stat().st_mtime)) if css_path.is_file() else "dev"
    runtime_path = preflight_result.settings.local_runtime_db_path if preflight_result.settings else None
    app.extensions["iam_file_watcher"] = None
    app.extensions["iam_refresh_lock"] = threading.Lock()
    if runtime_path:
        app.register_blueprint(create_admin_blueprint(runtime_path, discovery_file=discovery_path(preflight_result.settings.sharepoint_root_path), local_runtime_path=preflight_result.settings.local_runtime_db_path, published_runtime_path=preflight_result.settings.published_runtime_db_path, audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_master_blueprint(runtime_path, preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_user_blueprint(runtime_path, audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_identity_blueprint(runtime_path, discovery_file=discovery_path(preflight_result.settings.sharepoint_root_path), audit_path=preflight_result.settings.audit_folder_path))
        app.register_blueprint(create_request_blueprint(runtime_path, audit_path=preflight_result.settings.audit_folder_path))

    @app.before_request
    def enforce_session_revocation():
        if runtime_path and runtime_path.is_file() and session.get("iam_user") and session.get("iam_session_started_at"):
            if SessionService(runtime_path).is_revoked(str(session["iam_user"]), str(session["iam_session_started_at"])):
                session.clear()
                return redirect(url_for("login"))
            current = next((user for user in UserService(runtime_path).list_users() if user.username.lower() == str(session["iam_user"]).lower()), None)
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
        notification_service = NotificationService(runtime_path) if runtime_path and username and runtime_path.is_file() else None
        unread_count = notification_service.unread_count(username) if notification_service else 0
        recent_notifications = notification_service.list_for_user(username, unread_only=True)[:5] if notification_service else []
        return {
            "is_admin": bool({"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"} & {str(role).upper() for role in roles}),
            "unread_notification_count": unread_count,
            "recent_notifications": recent_notifications,
            "static_version": static_version,
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
        return render_template("auth/login.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), error=None)

    @app.post("/login")
    def sign_in():
        if not preflight_result.ok or not runtime_path:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
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
        return render_template("dashboard.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), username=username, roles=tuple(session.get("iam_roles", ())), overview=OverviewService(runtime_path).snapshot(str(username)), workspace_version=workspace.version(), workspace_message=request.args.get("refreshed"))

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
            return render_template("dashboard.html", sharepoint_path=str(preflight_result.settings.sharepoint_root_path), username=str(username), roles=tuple(session.get("iam_roles", ())), overview=OverviewService(runtime_path).snapshot(str(username)), workspace_version=workspace.version(), workspace_error=str(exc)), 409

    @app.get("/profile")
    def profile():
        if not session.get("iam_user"):
            return redirect(url_for("login"))
        return render_template("profile.html", username=str(session["iam_user"]), roles=tuple(session.get("iam_roles", ())), sharepoint_path=str(preflight_result.settings.sharepoint_root_path))

    @app.get("/notifications")
    def notifications_page():
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        service = NotificationService(runtime_path)
        return render_template("notifications.html", notifications=service.list_for_user(str(username)))

    @app.post("/notifications/<notification_id>/read")
    def notification_read(notification_id: str):
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        NotificationService(runtime_path).mark_read(str(username), notification_id)
        return redirect(url_for("notifications_page"))

    @app.post("/notifications/<notification_id>/resolve")
    def notification_resolve(notification_id: str):
        username = session.get("iam_user")
        if not username or not runtime_path or not runtime_path.is_file():
            return redirect(url_for("login"))
        NotificationService(runtime_path).resolve(str(username), notification_id)
        return redirect(url_for("notifications_page"))

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


def start_file_watcher(preflight_result: PreflightResult):
    if not preflight_result.settings:
        return None
    database_path = preflight_result.settings.local_runtime_db_path
    watcher = FileWatchService(database_path, preflight_result.settings.sharepoint_root_path).start()
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
        self._server = create_server(self.app, host=self.host, port=self.port, threads=4)
        self.port = int(self._server.effective_port)  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._run, name="iam-local-webapp", daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}/login"

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()  # type: ignore[attr-defined]
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None


def _serve_webapp_process(preflight_result: PreflightResult, ready_queue) -> None:
    """Serve the local app in a separate process from the Qt control panel."""
    shutdown_token = secrets.token_urlsafe(32)
    server_holder: dict[str, LocalWebAppServer] = {}

    def shutdown_server() -> None:
        server = server_holder.get("server")
        if server:
            server.stop()

    app = create_app(preflight_result, shutdown_callback=shutdown_server, shutdown_token=shutdown_token)
    watcher = start_file_watcher(preflight_result)
    app.extensions["iam_file_watcher"] = watcher
    server = LocalWebAppServer(app)
    server_holder["server"] = server
    url = server.start()
    webapp_pid_path().write_text(json.dumps({"pid": os.getpid(), "port": server.port, "token": shutdown_token}) + "\n", encoding="utf-8")
    ready_queue.put(url)
    try:
        if server._thread:
            server._thread.join()
    finally:
        if watcher:
            watcher.stop()
        server.stop()
        try:
            webapp_pid_path().unlink()
        except FileNotFoundError:
            pass


def launch_local_webapp_process(
    preflight_result: PreflightResult,
    *,
    open_browser: bool = True,
    startup_timeout: float = 10.0,
) -> tuple[multiprocessing.Process, str]:
    """Start Flask independently so the Qt launcher remains responsive."""
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    process = context.Process(target=_serve_webapp_process, args=(preflight_result, ready_queue), name="iam-flask-webapp", daemon=False)
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
    return process, url


def open_browser(url: str) -> None:
    webbrowser.open(url, new=2)
