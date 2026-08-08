"""
File: scripts/validate_environment.py
Purpose: Provides an operational utility for validate environment.
Responsibilities: Exposes or coordinates: main.
Dependencies: argparse, iam_automation
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.access_driver import available_odbc_drivers, select_access_driver
from iam_automation.config import DEFAULT_CONFIG_PATH, validation_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate IAM Automation POC environment.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    payload = validation_payload(config_path=args.config)
    drivers = available_odbc_drivers()
    selected_driver = select_access_driver(drivers)
    report = {
        "paths": payload,
        "odbc": {
            "drivers": drivers,
            "selected_access_driver": selected_driver,
            "ok": selected_driver is not None,
        },
    }
    print(json.dumps(report, indent=2))
    return 0 if payload["ok"] and selected_driver else 1


if __name__ == "__main__":
    raise SystemExit(main())
