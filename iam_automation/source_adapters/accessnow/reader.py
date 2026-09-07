"""Read AccessNow CSV and XLSX report rows."""

from __future__ import annotations

import csv
import io
import warnings
from pathlib import Path


def read_rows(path: Path, content: bytes) -> list[tuple[int, dict[str, object]]]:
    """Read rows from one report while preserving source row numbers."""
    if path.suffix.lower() == ".csv":
        text = content.decode("utf-8-sig", errors="replace")
        return [(number, dict(row)) for number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2)]
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("AccessNow XLSX ingestion requires openpyxl.") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        values = list(workbook.active.values)
        if not values:
            return []
        headers = [str(value or "").strip() for value in values[0]]
        return [
            (number, dict(zip(headers, row)))
            for number, row in enumerate(values[1:], start=2)
            if any(value not in (None, "") for value in row)
        ]
    finally:
        workbook.close()
