"""Compose unchanged legacy UI and runtime v2 under isolated URL prefixes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response

from ...application.parallel_engine.watcher import ParallelFileWatcher
from ...startup import PreflightResult
from ...webapp import create_app as create_legacy_app
from .parallel_engine_app import create_parallel_engine_app


class LegacyReadOnlyGateway:
    """Keep legacy pages available for reference while blocking its writes."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = str(environ.get("PATH_INFO", ""))
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method not in {"GET", "HEAD", "OPTIONS"} and not (method == "POST" and path.rstrip("/") == "/login"):
            response = Response(
                "Legacy mode is read-only in the parallel host. Use /engine for the new runtime.",
                status=405,
                content_type="text/plain; charset=utf-8",
                headers={"Allow": "GET, HEAD, OPTIONS"},
            )
            return response(environ, start_response)
        return self.app(environ, start_response)


@dataclass(frozen=True)
class ParallelHost:
    application: Any
    engine_app: Any
    watcher: ParallelFileWatcher


def create_parallel_host(preflight: PreflightResult) -> ParallelHost:
    """Compose the unchanged legacy Flask factory with the new `/engine` app.

    The legacy watcher is deliberately not started here. Its existing launcher
    and behavior remain unchanged outside this parallel host.
    """
    if not preflight.ok or not preflight.settings:
        raise RuntimeError("A successful, read-only SharePoint discovery preflight is required.")
    legacy_app = create_legacy_app(preflight)
    legacy_app.config["SESSION_COOKIE_PATH"] = "/"
    settings = preflight.settings
    engine_app = create_parallel_engine_app(
        settings.local_runtime_db_path,
        settings.sharepoint_root_path,
        shared_secret=legacy_app.secret_key,
    )
    engine_app.config["SESSION_COOKIE_NAME"] = legacy_app.config.get("SESSION_COOKIE_NAME", "session")
    engine_app.config["SESSION_COOKIE_PATH"] = "/"
    dispatcher = DispatcherMiddleware(
        engine_app,
        {"/legacy": LegacyReadOnlyGateway(legacy_app), "/engine": engine_app},
    )
    return ParallelHost(dispatcher, engine_app, engine_app.extensions["parallel_engine_watcher"])
