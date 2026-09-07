"""Read Roster Lock workbook rows without persistence concerns."""

from __future__ import annotations

import io
import warnings


def read_rows(content: bytes) -> list[dict[str, object]]:
    """Read non-empty rows from the active Roster Lock worksheet."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("Roster Lock ingestion requires openpyxl.") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Data Validation extension is not supported and will be removed",
            category=UserWarning,
        )
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        values = list(workbook.active.values)
        if not values:
            return []
        headers = [str(value or "").strip() for value in values[0]]
        return [
            dict(zip(headers, row))
            for row in values[1:]
            if any(value not in (None, "") for value in row)
        ]
    finally:
        workbook.close()
