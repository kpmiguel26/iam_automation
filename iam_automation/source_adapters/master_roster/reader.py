"""Read Master Roster workbook rows without persistence concerns."""

from __future__ import annotations

import io
import warnings


HEADER_SCAN_LIMIT = 12
REQUIRED_HEADERS = {"employee number", "employee name"}


def read_rows(content: bytes) -> list[tuple[int, dict[str, object]]]:
    """Read non-empty workbook rows and preserve their source row numbers."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("Master Roster ingestion requires openpyxl.") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Data Validation extension is not supported and will be removed",
            category=UserWarning,
        )
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        values = list(workbook.active.values)
        header_row = header_index(values)
        headers = unique_headers(values[header_row])
        return [
            (row_number, dict(zip(headers, row)))
            for row_number, row in enumerate(values[header_row + 1 :], start=header_row + 2)
            if any(value not in (None, "") for value in row)
        ]
    finally:
        workbook.close()


def header_index(values: list[tuple[object, ...]]) -> int:
    for index, row in enumerate(values[:HEADER_SCAN_LIMIT]):
        normalized = {str(value or "").strip().casefold() for value in row}
        if REQUIRED_HEADERS.issubset(normalized):
            return index
    raise ValueError("Master Roster workbook must contain Employee Number and Employee Name headers.")


def unique_headers(row: tuple[object, ...]) -> list[str]:
    counts: dict[str, int] = {}
    headers: list[str] = []
    for index, value in enumerate(row, start=1):
        base = str(value or "").strip() or f"Source Column {index}"
        counts[base] = counts.get(base, 0) + 1
        headers.append(base if counts[base] == 1 else f"{base} [{counts[base]}]")
    return headers
