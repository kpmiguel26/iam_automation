from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Blueprint, render_template, request, session

from ...application.user_service import UserService
from ...application.identity_service import IdentityService
from ...identity import ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, normalize_role


def create_user_blueprint(database_path: Path) -> Blueprint:
    blueprint = Blueprint("user_admin", __name__, url_prefix="/admin/users")
    service = UserService(database_path)

    def administrator_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN} & {normalize_role(str(role)) for role in session.get("iam_roles", ())}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def render(message: str | None = None, error: str | None = None):
        return render_template("admin/users.html", users=service.list_users(), message=message, error=error)

    @blueprint.get("")
    @administrator_required
    def users():
        return render()

    @blueprint.post("/create")
    @administrator_required
    def create_user():
        try:
            roles = request.form.get("roles", "").split(",")
            if ROLE_MASTER_ADMIN in {normalize_role(role) for role in roles} and ROLE_MASTER_ADMIN not in {normalize_role(role) for role in session.get("iam_roles", ())}:
                return render(error="Only MASTER_ADMIN can assign MASTER_ADMIN."), 403
            service.create_user(request.form.get("username", ""), request.form.get("display_name", ""), request.form.get("password", ""), roles)
            return render(message="Application user created.")
        except ValueError as exc:
            return render(error=str(exc)), 400

    @blueprint.post("/<username>/update")
    @administrator_required
    def update_user(username: str):
        try:
            roles = request.form.get("roles", "").split(",")
            if ROLE_MASTER_ADMIN in {normalize_role(role) for role in roles} and ROLE_MASTER_ADMIN not in {normalize_role(role) for role in session.get("iam_roles", ())}:
                return render(error="Only MASTER_ADMIN can assign MASTER_ADMIN."), 403
            service.update_user(username, display_name=request.form.get("display_name", ""), password=request.form.get("password", ""), roles=roles, active=request.form.get("active") == "1")
            return render(message=f"Application user updated: {username}")
        except ValueError as exc:
            return render(error=str(exc)), 400

    return blueprint


def create_identity_blueprint(database_path: Path) -> Blueprint:
    blueprint = Blueprint("identity_admin", __name__, url_prefix="/admin/windows-identities")
    service = IdentityService(database_path)

    def administrator_required(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            if not roles & {ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
                return "Administrator role required.", 403
            return view(*args, **kwargs)
        return wrapped

    def render(message: str | None = None, error: str | None = None):
        roles = {normalize_role(str(role)) for role in session.get("iam_roles", ())}
        return render_template("admin/windows_identities.html", identities=service.list_identities(), message=message, error=error, can_assign_master=ROLE_MASTER_ADMIN in roles)

    @blueprint.get("")
    @administrator_required
    def identities():
        return render()

    @blueprint.post("/save")
    @administrator_required
    def save_identity():
        try:
            roles = request.form.get("roles", "").split(",")
            can_assign_master = ROLE_MASTER_ADMIN in {normalize_role(str(role)) for role in session.get("iam_roles", ())}
            service.save_identity(request.form.get("username", ""), request.form.get("display_name", ""), roles, request.form.get("active", "1") == "1", can_assign_master=can_assign_master)
            return render(message="Windows identity saved.")
        except (ValueError, PermissionError) as exc:
            return render(error=str(exc)), 400

    return blueprint
