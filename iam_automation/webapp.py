from __future__ import annotations

import errno
import multiprocessing
import queue
import threading
import webbrowser
from dataclasses import dataclass
from typing import Callable

from .identity import CurrentUser, load_approved_users_from_sqlite, validate_current_user, validate_current_user_from_sqlite
from .startup import PreflightResult

try:  # Optional until the desktop/web UI dependencies are installed.
    from flask import Flask, Response, redirect, render_template_string, url_for
    from waitress import create_server
except ModuleNotFoundError:  # pragma: no cover - exercised when optional UI deps are absent
    Flask = None  # type: ignore[assignment,misc]
    Response = object  # type: ignore[assignment,misc]
    create_server = None  # type: ignore[assignment]
    render_template_string = None  # type: ignore[assignment]
    redirect = None  # type: ignore[assignment]
    url_for = None  # type: ignore[assignment]


LOGIN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>IAM Automation | Kaiser Permanente</title>
<style>
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #f4f6f8; color: #172033; }
.topbar { min-height: 92px; display: flex; align-items: center; padding: 18px 7vw; background: #0e2046; }
.topbar img { width: 245px; height: auto; display: block; }
.topbar-label { margin-left: auto; color: #dbe5f5; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; }
.page { width: min(100% - 32px, 760px); margin: 52px auto; }
.card { background: #fff; border: 1px solid #dce2ea; border-radius: 8px; box-shadow: 0 12px 30px rgba(14, 32, 70, .10); padding: 42px; }
.eyebrow { color: #007f82; font-size: 12px; font-weight: 700; letter-spacing: .12em; margin: 0 0 12px; text-transform: uppercase; }
h1 { color: #0e2046; font-size: 32px; margin: 0 0 10px; }
.intro { color: #5d6878; line-height: 1.6; margin: 0 0 28px; }
.verified { align-items: center; background: #eef8f3; border: 1px solid #b8e1ca; border-radius: 6px; color: #17613d; display: flex; gap: 12px; padding: 14px 16px; }
.verified-mark { align-items: center; background: #1d8a55; border-radius: 50%; color: #fff; display: flex; flex: 0 0 24px; font-weight: 700; height: 24px; justify-content: center; }
.profile { align-items: center; border-bottom: 1px solid #e4e8ee; display: flex; gap: 14px; padding: 26px 0; }
.avatar { align-items: center; background: #0e2046; border-radius: 50%; color: #fff; display: flex; font-size: 20px; font-weight: 700; height: 48px; justify-content: center; width: 48px; }
.profile strong, .profile small { display: block; }
.profile strong { color: #172033; font-size: 18px; }
.profile small { color: #6d7785; margin-top: 4px; }
.section-label { color: #667181; font-size: 12px; font-weight: 700; letter-spacing: .08em; margin: 26px 0 10px; text-transform: uppercase; }
.roles { display: flex; flex-wrap: wrap; gap: 8px; }
.role { background: #e5f3f2; border: 1px solid #b9ddda; border-radius: 999px; color: #075e61; font-size: 13px; font-weight: 700; padding: 7px 12px; }
.workspace { background: #f8fafc; border: 1px solid #e2e7ee; border-radius: 6px; padding: 14px 16px; }
.workspace span { color: #667181; display: block; font-size: 12px; margin-bottom: 6px; }
.workspace code { color: #26354b; display: block; font-size: 13px; overflow-wrap: anywhere; }
.footer { color: #7b8490; font-size: 12px; margin: 28px 0 0; text-align: center; }
@media (max-width: 600px) { .topbar { padding: 16px; } .topbar-label { display: none; } .page { margin: 24px auto; } .card { padding: 26px 22px; } h1 { font-size: 27px; } }
</style>
</head>
<body>
<header class="topbar"><img src="{{ url_for('static', filename='kaiser_permanente_logo.png') }}" alt="Kaiser Permanente"><span class="topbar-label">IAM Automation</span></header>
<main class="page"><section class="card">
<p class="eyebrow">Local access</p>
<h1>Welcome to IAM Automation</h1>
<p class="intro">Your local environment is ready and your identity has been verified for this workspace.</p>
<div class="verified"><span class="verified-mark">✓</span><span>Environment preflight completed successfully.</span></div>
<div class="profile"><span class="avatar">{{ username[:1]|upper }}</span><div><strong>{{ username }}</strong><small>Authenticated current user</small></div></div>
<p class="section-label">Assigned roles</p>
<div class="roles">{% for role in roles %}<span class="role">{{ role }}</span>{% endfor %}</div>
<p class="section-label">Active workspace</p>
<div class="workspace"><span>SharePoint / OneDrive synchronized path</span><code>{{ sharepoint_path }}</code></div>
<p class="footer">Kaiser Permanente · IAM Automation · Local session</p>
</section></main>
</body></html>
"""


def create_app(
    preflight_result: PreflightResult,
    *,
    approved_users_path=None,
    identity_validator: Callable[[object], CurrentUser] | None = None,
):
    if Flask is None:
        raise RuntimeError("Flask is required to start the local webapp. Install the UI dependencies first.")
    app = Flask(__name__)
    validator = identity_validator or validate_current_user
    user_path = approved_users_path or (preflight_result.settings.approved_users_path if preflight_result.settings else None)
    runtime_path = preflight_result.settings.local_runtime_db_path if preflight_result.settings else None

    def validate_login_user(path):
        if identity_validator:
            return identity_validator(path)
        if runtime_path and load_approved_users_from_sqlite(runtime_path):
            return validate_current_user_from_sqlite(runtime_path)
        return validator(path)

    @app.get("/health")
    def health():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        return {"status": "ok"}

    @app.get("/")
    def index():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        return redirect(url_for("login"))

    @app.get("/login")
    def login():
        if not preflight_result.ok or not user_path:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        try:
            user = validate_login_user(user_path)
        except PermissionError as exc:
            return {"status": "unauthorized", "message": str(exc)}, 403
        return render_template_string(
            LOGIN_TEMPLATE,
            sharepoint_path=str(preflight_result.settings.sharepoint_root_path),
            username=user.username,
            roles=user.roles,
        )

    return app


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
            # Waitress closes its selector during shutdown; Python can surface
            # that expected wake-up as EBADF from the serving thread.
            if exc.errno != errno.EBADF:
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


def launch_local_webapp(preflight_result: PreflightResult, *, open_browser: bool = True) -> LocalWebAppServer:
    app = create_app(preflight_result)
    server = LocalWebAppServer(app)
    url = server.start()
    if open_browser:
        webbrowser.open(url)
    return server


def _serve_webapp_process(preflight_result: PreflightResult, ready_queue) -> None:
    """Run Flask in the standalone child process after the Qt launcher exits."""
    app = create_app(preflight_result)
    server = LocalWebAppServer(app)
    url = server.start()
    ready_queue.put(url)
    try:
        server._thread.join()  # type: ignore[union-attr]
    finally:
        server.stop()


def launch_local_webapp_process(
    preflight_result: PreflightResult,
    *,
    open_browser: bool = True,
    startup_timeout: float = 10.0,
) -> tuple[multiprocessing.Process, str]:
    """Start Flask independently so the desktop preflight process can terminate."""
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    process = context.Process(
        target=_serve_webapp_process,
        args=(preflight_result, ready_queue),
        name="iam-flask-webapp",
        daemon=False,
    )
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
