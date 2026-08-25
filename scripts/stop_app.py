"""
File: scripts/stop_app.py
Purpose: Provides an operational utility for stop app.
Responsibilities: Exposes or coordinates: main.
Dependencies: urllib, iam_automation
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.webapp import webapp_pid_path


def main() -> int:
    pid_file = webapp_pid_path()
    if not pid_file.exists():
        print("IAM webapp is not running.")
        return 0
    try:
        data = json.loads(pid_file.read_text(encoding="utf-8"))
        request = Request(
            f"http://127.0.0.1:{int(data['port'])}/__internal/shutdown",
            method="POST",
            headers={"X-IAM-Shutdown-Token": str(data["token"])},
        )
        with urlopen(request, timeout=3) as response:
            print(response.read().decode("utf-8"))
        return 0
    except Exception as exc:
        print(f"Could not stop IAM webapp cleanly: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
#endfile
