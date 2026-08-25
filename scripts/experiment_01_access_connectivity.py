"""
File: scripts/experiment_01_access_connectivity.py
Purpose: Provides an operational utility for experiment 01 access connectivity.
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

from iam_automation.access_driver import connect_access


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 1: Access connectivity and basic CRUD.")
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    with connect_access(args.db_path, autocommit=False) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "CREATE TABLE poc_employee (employee_id TEXT(50) PRIMARY KEY, full_name TEXT(255), record_version INTEGER)"
            )
            results.append({"step": "create_table", "ok": True})
        except Exception as exc:
            results.append({"step": "create_table", "ok": False, "error": str(exc)})

        cursor.execute("DELETE FROM poc_employee WHERE employee_id = ?", ("POC001",))
        cursor.execute(
            "INSERT INTO poc_employee (employee_id, full_name, record_version) VALUES (?, ?, ?)",
            ("POC001", "Proof User", 1),
        )
        cursor.execute(
            "UPDATE poc_employee SET full_name = ?, record_version = record_version + 1 WHERE employee_id = ?",
            ("Proof User Updated", "POC001"),
        )
        row = cursor.execute(
            "SELECT employee_id, full_name, record_version FROM poc_employee WHERE employee_id = ?",
            ("POC001",),
        ).fetchone()
        conn.rollback()
        after_rollback = cursor.execute(
            "SELECT employee_id FROM poc_employee WHERE employee_id = ?",
            ("POC001",),
        ).fetchone()
        results.append(
            {
                "step": "crud_and_rollback",
                "ok": row is not None and after_rollback is None,
                "row_before_rollback": list(row) if row else None,
                "row_after_rollback": list(after_rollback) if after_rollback else None,
            }
        )

    print(json.dumps({"experiment": "access_connectivity", "results": results}, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
#endfile
