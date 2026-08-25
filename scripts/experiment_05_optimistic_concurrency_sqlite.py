"""
File: scripts/experiment_05_optimistic_concurrency_sqlite.py
Purpose: Provides an operational utility for experiment 05 optimistic concurrency sqlite.
Responsibilities: Exposes or coordinates: init_db, main.
Dependencies: argparse
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
import sqlite3
from pathlib import Path


def init_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employee (
                employee_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                record_version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO employee (employee_id, full_name, record_version) VALUES (?, ?, ?)",
            ("POC001", "Original Name", 1),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 5: optimistic concurrency demonstration.")
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    init_db(args.db_path)

    with sqlite3.connect(args.db_path) as conn:
        original = conn.execute(
            "SELECT employee_id, full_name, record_version FROM employee WHERE employee_id = ?",
            ("POC001",),
        ).fetchone()
        conn.execute(
            "UPDATE employee SET full_name = ?, record_version = record_version + 1 WHERE employee_id = ?",
            ("Concurrent Change", "POC001"),
        )
        cursor = conn.execute(
            """
            UPDATE employee
            SET full_name = ?, record_version = record_version + 1
            WHERE employee_id = ? AND record_version = ?
            """,
            ("Stale Update", "POC001", original[2]),
        )
        conflict_detected = cursor.rowcount == 0

    print(json.dumps({"original_version": original[2], "conflict_detected": conflict_detected}, indent=2))
    return 0 if conflict_detected else 1


if __name__ == "__main__":
    raise SystemExit(main())
#endfile
