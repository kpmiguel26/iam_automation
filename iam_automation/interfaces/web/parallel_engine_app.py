"""Authenticated web surface for the independent parallel ingestion engine."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, Flask, abort, flash, redirect, render_template, request, session, url_for

from ...application.parallel_engine.database import connect, initialize_engine_schema
from ...application.parallel_engine.feature_flags import FILE_PROCESSING_ENABLED, PROCESSING_PAUSED_MESSAGE
from ...application.parallel_engine.templates import RuntimeTemplateCatalog
from ...application.parallel_engine.watcher import ParallelFileWatcher
from ...application.parallel_engine.engine import ParallelIngestionEngine
from ...application.session_service import SessionService
from ...application.temporary_super_operator_service import TemporarySuperOperatorService
from ...application.user_service import UserService


ADMIN_ROLES = {"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"}
APPROVER_ROLES = {"APPLICATION_ADMIN", "MASTER_ADMIN"}


def create_parallel_engine_blueprint(
    database_path: Path,
    sharepoint_root: Path,
    *,
    url_prefix: str = "/engine",
    dashboard_template: str = "parallel_engine/dashboard_integrated.html",
    login_url: str = "/login",
) -> Blueprint:
    """Register runtime v2 routes inside the normal authenticated application."""
    database_path = Path(database_path)
    root = Path(sharepoint_root).expanduser().resolve()
    initialize_engine_schema(database_path)
    blueprint = Blueprint("parallel_engine", __name__, url_prefix=url_prefix)
    catalog = RuntimeTemplateCatalog(database_path, root)
    engine = ParallelIngestionEngine(database_path, root)
    watcher = ParallelFileWatcher(engine, interval_seconds=120.0)

    def require_user() -> None:
        if not session.get("iam_user"):
            abort(401)

    def require_admin() -> None:
        require_user()
        roles = {str(role).strip().upper() for role in session.get("iam_roles", ())}
        if not roles & ADMIN_ROLES:
            abort(403)

    def require_approver() -> str:
        require_user()
        roles = {str(role).strip().upper() for role in session.get("iam_roles", ())}
        if not roles & APPROVER_ROLES:
            abort(403)
        return str(session["iam_user"])

    @blueprint.before_request
    def protect_engine_session():
        username = session.get("iam_user")
        session_started = session.get("iam_session_started_at")
        if username and session_started:
            if SessionService(database_path).is_revoked(str(username), str(session_started)):
                session.clear()
                abort(401)
            current = UserService(database_path).get_user(str(username))
            if not current or not current.active or current.status != "ACTIVE":
                session.clear()
                abort(401)
            roles = TemporarySuperOperatorService(database_path).effective_roles(current.username, current.roles)
            session["iam_roles"] = list(roles)
            session["is_admin"] = bool(ADMIN_ROLES & {str(role).upper() for role in roles})
        return None

    @blueprint.errorhandler(401)
    def engine_login_required(_error):
        return redirect(login_url)

    @blueprint.get("/")
    def index():
        if not session.get("iam_user"):
            return redirect(login_url)
        return redirect(url_for("parallel_engine.dashboard"))

    @blueprint.get("/dashboard")
    def dashboard():
        require_admin()
        connection = connect(database_path)
        try:
            health_row = connection.execute("SELECT * FROM engine_v2_watcher_state WHERE singleton_id = 1").fetchone()
            batches = [dict(row) for row in connection.execute("SELECT * FROM engine_v2_batches ORDER BY started_at_utc DESC LIMIT 20").fetchall()]
            observations = [dict(row) for row in connection.execute("SELECT * FROM engine_v2_file_observations ORDER BY last_seen_at_utc DESC LIMIT 30").fetchall()]
            approved = connection.execute(
                "SELECT COUNT(*) FROM engine_v2_object_template_approvals a JOIN employee_template_versions v ON v.employee_template_version_id = a.object_template_version_id WHERE v.template_key='EMPLOYEE_PROFILE'"
            ).fetchone()[0]
        finally:
            connection.close()
        configuration_error = ""
        try:
            configuration = catalog.load()
            sources = configuration.sources if configuration else ()
            object_name = configuration.object_template.definition.get("object_name", "") if configuration else ""
        except Exception as exc:
            sources = ()
            object_name = ""
            configuration_error = str(exc)
        return render_template(
            dashboard_template, username=session.get("iam_user"), health=dict(health_row) if health_row else None,
            batches=batches, observations=observations, sources=sources, object_name=object_name,
            approved_object_templates=approved, configuration_error=configuration_error,
            csrf_token=session.get("iam_csrf_token", session.get("parallel_engine_csrf_token", "")),
            can_authorize_processing=FILE_PROCESSING_ENABLED and bool(
                {str(role).strip().upper() for role in session.get("iam_roles", ())} & APPROVER_ROLES
            ),
            processing_enabled=FILE_PROCESSING_ENABLED,
        )

    @blueprint.post("/files/<observation_id>/process")
    def authorize_file_processing(observation_id: str):
        actor = require_approver()
        return_to = request.form.get("return_to", "")
        parsed_return_to = urlsplit(return_to)
        if not FILE_PROCESSING_ENABLED:
            flash(PROCESSING_PAUSED_MESSAGE, "warning")
            if parsed_return_to.path == "/employees/source-updates" and not parsed_return_to.netloc:
                return redirect(return_to)
            return redirect(url_for("parallel_engine.dashboard"))
        try:
            result = watcher.authorize_and_process(observation_id, actor)
        except (OSError, RuntimeError, ValueError) as exc:
            flash(f"File was not processed: {exc}", "danger")
        else:
            flash(
                f"Authorized and processed {Path(result.file_path).name}: "
                f"{result.total_rows} row(s), {result.objects_created} new object(s), "
                f"{result.objects_linked} linked object(s).",
                "success",
            )
        if parsed_return_to.path == "/employees/source-updates" and not parsed_return_to.netloc:
            return redirect(return_to)
        return redirect(url_for("parallel_engine.dashboard"))

    @blueprint.get("/status")
    def status():
        require_admin()
        connection = connect(database_path)
        try:
            health = connection.execute("SELECT * FROM engine_v2_watcher_state WHERE singleton_id = 1").fetchone()
            counts = {
                "batches": int(connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0]),
                "objects": int(connection.execute("SELECT COUNT(*) FROM engine_v2_objects").fetchone()[0]),
                "evidence": int(connection.execute("SELECT COUNT(*) FROM engine_v2_evidence").fetchone()[0]),
            }
        finally:
            connection.close()
        return {"watcher": dict(health) if health else {"status": "STARTING"}, **counts}

    blueprint.parallel_engine_extensions = {
        "parallel_engine_catalog": catalog,
        "parallel_engine": engine,
        "parallel_engine_watcher": watcher,
    }
    return blueprint


def create_parallel_engine_app(database_path: Path, sharepoint_root: Path, *, shared_secret: str | bytes | None = None) -> Flask:
    """Standalone compatibility host for the former `/engine` runtime surface."""
    app = Flask(__name__, template_folder="../../templates", static_folder="../../static/parallel_engine", static_url_path="/static")
    app.secret_key = shared_secret or secrets.token_urlsafe(32)
    app.config["SESSION_COOKIE_PATH"] = "/"
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    csrf_key = "parallel_engine_csrf_token"

    def csrf_token() -> str:
        token = session.get(csrf_key)
        if not token:
            token = secrets.token_urlsafe(32)
            session[csrf_key] = token
        return str(token)

    @app.before_request
    def protect_standalone_posts():
        if request.method != "POST":
            return None
        submitted = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not submitted or not secrets.compare_digest(str(submitted), csrf_token()):
            return {"status": "invalid_csrf_token", "message": "The form security token is missing or invalid."}, 400
        return None

    @app.after_request
    def add_standalone_csrf(response):
        if response.mimetype == "text/html":
            body = response.get_data(as_text=True)
            field = f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'
            import re
            body = re.sub(r'(<form\b(?=[^>]*\bmethod\s*=\s*["\']post["\'])[^>]*>)', rf"\1{field}", body, flags=re.IGNORECASE)
            response.set_data(body)
        return response

    blueprint = create_parallel_engine_blueprint(
        database_path,
        sharepoint_root,
        url_prefix="",
        dashboard_template="parallel_engine/dashboard.html",
        login_url="/legacy/login",
    )
    app.register_blueprint(blueprint)
    app.extensions.update(blueprint.parallel_engine_extensions)
    return app
