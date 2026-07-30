from __future__ import annotations

import os
import traceback
from pathlib import Path


def main() -> int:
    from iam_automation.qt_startup import run_desktop_app

    return run_desktop_app()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        # Ctrl+C is a normal local shutdown action. Ask the child webapp to
        # stop before Python's multiprocessing cleanup waits on it.
        try:
            from iam_automation.webapp import stop_local_webapp

            stop_local_webapp()
        except Exception:
            pass
        raise SystemExit(130)
    except Exception:
        log_path = Path(os.environ.get("IAM_LAUNCHER_LOG", Path.cwd() / ".iam_launcher.log"))
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                traceback.print_exc(file=log_file)
        except OSError:
            pass
        raise
