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
    except Exception:
        log_path = Path(os.environ.get("IAM_LAUNCHER_LOG", Path.cwd() / ".iam_launcher.log"))
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                traceback.print_exc(file=log_file)
        except OSError:
            pass
        raise
