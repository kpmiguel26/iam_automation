from __future__ import annotations

from pathlib import Path
from typing import Any


ACCESS_DRIVER_CANDIDATES = (
    "Microsoft Access Driver (*.mdb, *.accdb)",
    "Microsoft Access Driver (*.mdb)",
)


def connection_string(db_path: Path, driver: str = ACCESS_DRIVER_CANDIDATES[0]) -> str:
    return f"DRIVER={{{driver}}};DBQ={db_path};"


def available_odbc_drivers() -> list[str]:
    try:
        import pyodbc  # type: ignore
    except Exception:
        return []
    return list(pyodbc.drivers())


def select_access_driver(drivers: list[str] | None = None) -> str | None:
    installed = drivers if drivers is not None else available_odbc_drivers()
    for candidate in ACCESS_DRIVER_CANDIDATES:
        if candidate in installed:
            return candidate
    return None


def connect_access(db_path: Path, *, autocommit: bool = False) -> Any:
    try:
        import pyodbc  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Windows host
        raise RuntimeError("pyodbc is required for Access connectivity tests.") from exc
    driver = select_access_driver()
    if not driver:
        raise RuntimeError("Microsoft Access ODBC driver was not found.")
    return pyodbc.connect(connection_string(db_path, driver), autocommit=autocommit)
