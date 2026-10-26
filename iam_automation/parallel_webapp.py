"""Entrypoint for the composed legacy-reference and parallel runtime host."""

from __future__ import annotations

import logging
import os
import webbrowser

from waitress import create_server

from .interfaces.web.parallel_host import create_parallel_host
from .startup import StartupController


LOGGER = logging.getLogger("iam.parallel_webapp")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    preflight = StartupController().discover_sharepoint()
    if not preflight.ok or not preflight.settings:
        LOGGER.error("Parallel host could not discover a configured SharePoint root: %s", preflight.message)
        return 2
    if not preflight.settings.local_runtime_db_path.is_file():
        LOGGER.error("Local runtime SQLite is missing. Start the existing application once to initialize its local runtime, then retry.")
        return 2

    host = create_parallel_host(preflight)
    port = int(os.environ.get("IAM_PARALLEL_ENGINE_PORT", "0"))
    server = create_server(host.application, host="127.0.0.1", port=port, threads=4)
    url = f"http://127.0.0.1:{server.effective_port}/legacy/login"
    host.watcher.start()
    LOGGER.info("Parallel host ready: %s (engine: http://127.0.0.1:%s/engine/)", url, server.effective_port)
    try:
        webbrowser.open(url)
        server.run()
    except KeyboardInterrupt:
        LOGGER.info("Parallel host stopping.")
    finally:
        host.watcher.stop()
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
