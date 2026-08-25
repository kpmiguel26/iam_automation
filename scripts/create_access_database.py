"""
File: scripts/create_access_database.py
Purpose: Provides an operational utility for create access database.
Responsibilities: Exposes or coordinates: main.
Dependencies: argparse, iam_automation
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iam_automation.database import access_schema_statements, initialize_access_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or initialize the Microsoft Access master database.")
    parser.add_argument("database", type=Path, help="Path to the .accdb file.")
    parser.add_argument("--driver", help="Optional Access ODBC driver name.")
    parser.add_argument("--show-schema", action="store_true", help="Print the Access DDL without touching the database.")
    args = parser.parse_args()

    if args.show_schema:
        print("\n\n".join(access_schema_statements()))
        return 0

    try:
        print(json.dumps(initialize_access_database(args.database, driver=args.driver), indent=2))
    except Exception as exc:
        parser.exit(1, f"Access database initialization failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#endfile
