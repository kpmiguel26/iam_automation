from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, session

from ...application.employee_service import EmployeeService


def create_employee_blueprint(database_path: Path) -> Blueprint:
    blueprint = Blueprint("employees", __name__, url_prefix="/employees")
    service = EmployeeService(database_path)

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return "Application login required.", 401
            return view(*args, **kwargs)
        return wrapped

    @blueprint.get("")
    @authenticated
    def employee_directory():
        search = request.args.get("q", "")
        status = request.args.get("status", "ALL")
        vendor = request.args.get("vendor", "ALL")
        statuses, vendors = service.filter_values()
        # Load the local canonical directory once so the page can filter as the
        # user types without a request for every keystroke.
        workers = service.list_workers()
        return render_template("employees/list.html", workers=workers, statuses=statuses, vendors=vendors, filters={"q": search, "status": status, "vendor": vendor})

    @blueprint.get("/<worker_id>")
    @authenticated
    def employee_detail(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/detail.html", **detail)

    return blueprint
