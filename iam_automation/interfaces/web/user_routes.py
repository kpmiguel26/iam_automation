from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, redirect, render_template_string, request, session, url_for

from ...application.user_service import UserService
from ...identity import ROLE_ADMINISTRATOR


USER_ADMIN_TEMPLATE = """
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>IAM Automation | Users</title><style>
body{margin:0;background:#f4f6f8;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.top{background:#0e2046;color:#fff;padding:22px 7vw;display:flex;justify-content:space-between}.page{max-width:1100px;margin:36px auto;padding:0 24px}.panel{background:#fff;border:1px solid #dce2ea;border-radius:8px;padding:24px;margin-bottom:20px}h1{color:#0e2046}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}input,select{padding:10px;border:1px solid #cbd4df;border-radius:5px;width:100%;box-sizing:border-box}button{padding:10px 14px;border:0;border-radius:5px;background:#0e2046;color:#fff;font-weight:700;cursor:pointer}.danger{background:#8e2e2e}.msg{padding:12px;background:#eef8f3;color:#17613d;margin-bottom:16px}.error{padding:12px;background:#fff1f0;color:#9d3028;margin-bottom:16px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #e4e8ee}.tag{background:#e5f3f2;color:#075e61;border-radius:999px;padding:4px 8px;font-size:12px}.muted{color:#697587}
</style></head><body><header class="top"><strong>IAM AUTOMATION</strong><a href="{{ url_for('dashboard') }}" style="color:#fff">Workspace</a></header><main class="page"><h1>User administration</h1><p class="muted">Manage local application accounts and assigned roles.</p>{% if message %}<div class="msg">{{ message }}</div>{% endif %}{% if error %}<div class="error">{{ error }}</div>{% endif %}
<section class="panel"><h2>Create application user</h2><form method="post" action="{{ url_for('user_admin.create_user') }}"><div class="grid"><input name="username" placeholder="Username" required><input name="display_name" placeholder="Display name"><input name="password" type="password" placeholder="Temporary password" required><input name="roles" placeholder="Roles, e.g. REQUESTER" required></div><p><button type="submit">Create user</button></p></form></section>
<section class="panel"><h2>Application users</h2><table><tr><th>Username</th><th>Display name</th><th>Roles</th><th>Status</th><th>Update</th></tr>{% for user in users %}<tr><form method="post" action="{{ url_for('user_admin.update_user', username=user.username) }}"><td>{{ user.username }}</td><td><input name="display_name" value="{{ user.display_name }}"></td><td><input name="roles" value="{{ ', '.join(user.roles) }}"></td><td><select name="active"><option value="1" {% if user.active %}selected{% endif %}>Active</option><option value="0" {% if not user.active %}selected{% endif %}>Inactive</option></select></td><td><input name="password" type="password" placeholder="Keep password"><button type="submit">Save</button></td></form></tr>{% endfor %}</table></section></main></body></html>
"""


def create_user_blueprint(database_path: Path) -> Blueprint:
    blueprint = Blueprint("user_admin", __name__, url_prefix="/admin/users")
    service = UserService(database_path)

    def administrator_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if ROLE_ADMINISTRATOR not in {str(role).upper() for role in session.get("iam_roles", ())}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def render(message: str | None = None, error: str | None = None):
        return render_template_string(USER_ADMIN_TEMPLATE, users=service.list_users(), message=message, error=error)

    @blueprint.get("")
    @administrator_required
    def users():
        return render()

    @blueprint.post("/create")
    @administrator_required
    def create_user():
        try:
            service.create_user(request.form.get("username", ""), request.form.get("display_name", ""), request.form.get("password", ""), request.form.get("roles", "").split(","))
            return render(message="Application user created.")
        except ValueError as exc:
            return render(error=str(exc)), 400

    @blueprint.post("/<username>/update")
    @administrator_required
    def update_user(username: str):
        try:
            service.update_user(username, display_name=request.form.get("display_name", ""), password=request.form.get("password", ""), roles=request.form.get("roles", "").split(","), active=request.form.get("active") == "1")
            return render(message=f"Application user updated: {username}")
        except ValueError as exc:
            return render(error=str(exc)), 400

    return blueprint
