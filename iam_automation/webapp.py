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

from .identity import CurrentUser, validate_app_user_from_sqlite
from .startup import PreflightResult

try:  # Optional until the desktop/web UI dependencies are installed.
    from flask import Flask, Response, redirect, render_template_string, request, session, url_for
    from waitress import create_server
except ModuleNotFoundError:  # pragma: no cover - exercised when optional UI deps are absent
    Flask = None  # type: ignore[assignment,misc]
    Response = object  # type: ignore[assignment,misc]
    create_server = None  # type: ignore[assignment]
    render_template_string = None  # type: ignore[assignment]
    redirect = None  # type: ignore[assignment]
    url_for = None  # type: ignore[assignment]
    request = session = None  # type: ignore[assignment]


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
.signin { border: 0; border-radius: 6px; background: #0e2046; color: #fff; cursor: pointer; font-size: 15px; font-weight: 700; margin-top: 28px; padding: 13px 18px; width: 100%; }
.signin:hover { background: #183568; }
.signin-input { border: 1px solid #cbd4df; border-radius: 5px; display: block; font-size: 16px; margin-bottom: 12px; padding: 12px; width: 100%; }
.error { background: #fff1f0; border: 1px solid #efb9b3; border-radius: 6px; color: #9d3028; margin-bottom: 18px; padding: 12px 14px; }
@media (max-width: 600px) { .topbar { padding: 16px; } .topbar-label { display: none; } .page { margin: 24px auto; } .card { padding: 26px 22px; } h1 { font-size: 27px; } }
</style>
</head>
<body>
<header class="topbar"><img src="{{ url_for('static', filename='kaiser_permanente_logo.png') }}" alt="Kaiser Permanente"><span class="topbar-label">IAM Automation</span></header>
<main class="page"><section class="card">
<p class="eyebrow">Local access</p>
<h1>{% if authenticated %}Welcome to IAM Automation{% else %}Sign in to IAM Automation{% endif %}</h1>
<p class="intro">{% if authenticated %}Your local application session is active.{% else %}The Windows identity gate has passed. Sign in with your IAM Automation application account to continue.{% endif %}</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<div class="verified"><span class="verified-mark">✓</span><span>Environment preflight completed successfully.</span></div>
<div class="profile"><span class="avatar">{% if authenticated %}{{ username[:1]|upper }}{% else %}IAM{% endif %}</span><div><strong>{% if authenticated %}{{ username }}{% else %}Application account{% endif %}</strong><small>{% if authenticated %}Authenticated application user{% else %}Separate from the Windows identity{% endif %}</small></div></div>
<p class="section-label">Assigned roles</p>
<div class="roles">{% for role in roles %}<span class="role">{{ role }}</span>{% endfor %}</div>
<p class="section-label">Active workspace</p>
<div class="workspace"><span>SharePoint / OneDrive synchronized path</span><code>{{ sharepoint_path }}</code></div>
{% if not authenticated %}<label class="section-label" for="app-username">Application username</label><input class="signin-input" id="app-username" name="username" form="login-form" autocomplete="username" required><label class="section-label" for="app-password">Application password</label><input class="signin-input" id="app-password" name="password" type="password" form="login-form" autocomplete="current-password" required><form id="login-form" method="post" action="{{ url_for('login') }}"><button class="signin" type="submit">Sign in</button></form>{% endif %}
<p class="footer">Kaiser Permanente · IAM Automation · Local session</p>
</section></main>
</body></html>
"""


def webapp_pid_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".iam_webapp.pid"


def stop_local_webapp() -> str:
    data = json.loads(webapp_pid_path().read_text(encoding="utf-8"))
    request = Request(
        f"http://127.0.0.1:{int(data['port'])}/__internal/shutdown",
        method="POST",
        headers={"X-IAM-Shutdown-Token": str(data["token"])},
    )
    with urlopen(request, timeout=3) as response:
        return response.read().decode("utf-8")


DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>IAM Automation | Workspace</title>
<style>
:root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #f4f6f8; color: #172033; }
.topbar { align-items: center; background: #0e2046; display: flex; min-height: 76px; padding: 14px 6vw; }
.topbar img { display: block; width: 210px; }
.nav { align-items: center; display: flex; gap: 22px; margin-left: auto; }
.nav a { color: #dbe5f5; font-size: 13px; text-decoration: none; }
.nav a:hover { color: #fff; }
.logout { border: 1px solid #88a1cb; border-radius: 5px; color: #fff !important; padding: 8px 12px; }
.page { margin: 0 auto; max-width: 1180px; padding: 42px 24px 56px; }
.heading { align-items: end; display: flex; justify-content: space-between; margin-bottom: 30px; }
.eyebrow { color: #007f82; font-size: 12px; font-weight: 700; letter-spacing: .12em; margin: 0 0 10px; text-transform: uppercase; }
h1 { color: #0e2046; font-size: 32px; margin: 0; }
.subtle { color: #697587; margin: 8px 0 0; }
.session { align-items: center; background: #eef8f3; border: 1px solid #b8e1ca; border-radius: 6px; color: #17613d; display: flex; font-size: 13px; gap: 8px; padding: 9px 12px; }
.dot { background: #1d8a55; border-radius: 50%; height: 8px; width: 8px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(3, 1fr); }
.panel { background: #fff; border: 1px solid #dce2ea; border-radius: 8px; padding: 22px; }
.panel h2 { color: #0e2046; font-size: 16px; margin: 0 0 16px; }
.metric { color: #172033; font-size: 20px; font-weight: 700; overflow-wrap: anywhere; }
.label { color: #778292; font-size: 12px; margin-bottom: 7px; }
.role { background: #e5f3f2; border: 1px solid #b9ddda; border-radius: 999px; color: #075e61; display: inline-block; font-size: 12px; font-weight: 700; margin: 3px 4px 0 0; padding: 6px 9px; }
.section { margin-top: 30px; }
.section-title { color: #0e2046; font-size: 20px; margin: 0 0 14px; }
.work-grid { display: grid; gap: 16px; grid-template-columns: repeat(4, 1fr); }
.work-item { background: #fff; border: 1px solid #dce2ea; border-radius: 8px; min-height: 138px; padding: 20px; }
.work-item h3 { color: #0e2046; font-size: 15px; margin: 0 0 8px; }
.work-item p { color: #697587; font-size: 13px; line-height: 1.45; margin: 0; }
.badge { color: #788392; display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .06em; margin-top: 16px; text-transform: uppercase; }
.empty { background: #fff; border: 1px dashed #bdc7d4; border-radius: 8px; color: #697587; padding: 26px; text-align: center; }
@media (max-width: 800px) { .heading { align-items: start; flex-direction: column; gap: 16px; } .grid, .work-grid { grid-template-columns: 1fr; } .nav { gap: 12px; } .topbar { padding: 14px 20px; } .topbar img { width: 180px; } }
</style>
</head>
<body>
<header class="topbar"><img src="{{ url_for('static', filename='kaiser_permanente_logo.png') }}" alt="Kaiser Permanente"><nav class="nav"><a href="{{ url_for('dashboard') }}">Workspace</a><a class="logout" href="{{ url_for('logout') }}">Sign out</a></nav></header>
<main class="page">
<div class="heading"><div><p class="eyebrow">IAM Automation</p><h1>Workspace overview</h1><p class="subtle">A controlled workspace for identity and access operations.</p></div><div class="session"><span class="dot"></span>Session active</div></div>
<section class="grid">
<article class="panel"><div class="label">Current user</div><div class="metric">{{ username }}</div></article>
<article class="panel"><div class="label">Effective roles</div><div>{% for role in roles %}<span class="role">{{ role }}</span>{% endfor %}</div></article>
<article class="panel"><div class="label">Connected workspace</div><div class="metric" style="font-size:14px; font-weight:600;">{{ sharepoint_path }}</div></article>
</section>
<section class="section"><h2 class="section-title">Work areas</h2><div class="work-grid">
<article class="work-item"><h3>Request intake</h3><p>Manage incoming IAM requests and their lifecycle.</p><span class="badge">Preparing</span></article>
<article class="work-item"><h3>User administration</h3><p>Manage approved users, roles and controlled profiles.</p><span class="badge">Preparing</span></article>
<article class="work-item"><h3>Templates</h3><p>Review source templates and generated exports.</p><span class="badge">Preparing</span></article>
<article class="work-item"><h3>Audit and governance</h3><p>Review activity, approvals, backups and publication history.</p><span class="badge">Preparing</span></article>
</div></section>
<section class="section"><h2 class="section-title">Recent activity</h2><div class="empty">No activity has been recorded in this session yet.</div></section>
</main>
</body></html>
"""


def create_app(
    preflight_result: PreflightResult,
    *,
    app_authenticator: Callable[[str, str], CurrentUser] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    shutdown_token: str | None = None,
):
    if Flask is None:
        raise RuntimeError("Flask is required to start the local webapp. Install the UI dependencies first.")
    app = Flask(__name__)
    app.secret_key = secrets.token_urlsafe(32)
    runtime_path = preflight_result.settings.local_runtime_db_path if preflight_result.settings else None

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
            threading.Thread(target=shutdown_callback, name="iam-webapp-shutdown", daemon=True).start()
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
        return render_template_string(
            LOGIN_TEMPLATE,
            sharepoint_path=str(preflight_result.settings.sharepoint_root_path),
            username="",
            roles=(),
            authenticated=False,
            error=None,
        )

    @app.post("/login")
    def sign_in():
        if not preflight_result.ok or not runtime_path:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        try:
            username = str(request.form.get("username", ""))
            password = str(request.form.get("password", ""))
            user = app_authenticator(username, password) if app_authenticator else validate_app_user_from_sqlite(runtime_path, username, password)
        except PermissionError as exc:
            return render_template_string(
                LOGIN_TEMPLATE,
                sharepoint_path=str(preflight_result.settings.sharepoint_root_path),
                username="",
                roles=(),
                authenticated=False,
                error=str(exc),
            ), 403
        session.clear()
        session["iam_user"] = user.username
        session["iam_roles"] = list(user.roles)
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        if not preflight_result.ok:
            return {"status": "blocked", "message": "SharePoint preflight has not passed."}, 503
        username = session.get("iam_user")
        if not username:
            return redirect(url_for("login"))
        return render_template_string(
            DASHBOARD_TEMPLATE,
            sharepoint_path=str(preflight_result.settings.sharepoint_root_path),
            username=username,
            roles=tuple(session.get("iam_roles", ())),
        )

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

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
            # that expected wake-up as EBADF/WSAENOTSOCK from the serving thread.
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


def launch_local_webapp(preflight_result: PreflightResult, *, open_browser: bool = True) -> LocalWebAppServer:
    app = create_app(preflight_result)
    server = LocalWebAppServer(app)
    url = server.start()
    if open_browser:
        webbrowser.open(url)
    return server


def _serve_webapp_process(preflight_result: PreflightResult, ready_queue) -> None:
    """Run Flask in the standalone child process after the Qt launcher exits."""
    shutdown_token = secrets.token_urlsafe(32)
    server_holder = {}

    def shutdown_server() -> None:
        server_holder["server"].stop()

    app = create_app(preflight_result, shutdown_callback=shutdown_server, shutdown_token=shutdown_token)
    server = LocalWebAppServer(app)
    server_holder["server"] = server
    url = server.start()
    webapp_pid_path().write_text(
        json.dumps({"pid": os.getpid(), "port": server.port, "token": shutdown_token}) + "\n",
        encoding="utf-8",
    )
    ready_queue.put(url)
    try:
        server._thread.join()  # type: ignore[union-attr]
    finally:
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
