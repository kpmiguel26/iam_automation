from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..access_driver import ACCESS_DRIVER_CANDIDATES, connection_string, select_access_driver
from .schema import access_schema_statements


class AccessDatabaseInitializationError(RuntimeError):
    pass


def _create_empty_access_file(path: Path) -> None:
    """Create an empty .accdb through ADOX; Access ODBC alone cannot create files."""
    if os.name != "nt":
        raise AccessDatabaseInitializationError(
            "Creating an Access .accdb requires Windows with Microsoft Access Database Engine/ADOX. "
            "Use the generated schema on macOS and initialize the file on Windows."
        )
    try:
        import win32com.client  # type: ignore[import-not-found]
    except Exception as exc:
        raise AccessDatabaseInitializationError(
            "pywin32 is required to create a new Access database. Install it on the Windows build machine."
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog = win32com.client.Dispatch("ADOX.Catalog")
    provider = "Microsoft.ACE.OLEDB.12.0"
    catalog.Create(f"Provider={provider};Data Source={path};")


def initialize_access_database(db_path: Path, *, driver: str | None = None) -> dict[str, Any]:
    """Create the Access file when needed and apply the initial schema idempotently."""
    db_path = db_path.expanduser().resolve()
    if db_path.suffix.lower() != ".accdb":
        raise AccessDatabaseInitializationError(f"Access database must use .accdb: {db_path}")
    if not db_path.exists():
        _create_empty_access_file(db_path)
    selected_driver = driver or select_access_driver()
    if not selected_driver:
        raise AccessDatabaseInitializationError(
            f"Microsoft Access ODBC driver not found. Expected one of: {', '.join(ACCESS_DRIVER_CANDIDATES)}"
        )
    try:
        import pyodbc  # type: ignore[import-not-found]
        with pyodbc.connect(connection_string(db_path, selected_driver), autocommit=False) as connection:
            cursor = connection.cursor()
            existing = {str(row.table_name) for row in cursor.tables(tableType="TABLE")}
            created: list[str] = []
            skipped: list[str] = []
            for statement in access_schema_statements():
                table_name = statement.split()[2] if statement.upper().startswith("CREATE TABLE") else ""
                if table_name and table_name in existing:
                    skipped.append(table_name)
                    continue
                if statement.upper().startswith("INSERT INTO TBL_APPMETADATA"):
                    metadata = cursor.execute(
                        "SELECT MetadataKey FROM tbl_AppMetadata WHERE MetadataKey = ?", ("schema_version",)
                    ).fetchone()
                    if metadata:
                        skipped.append("schema_version")
                        continue
                try:
                    cursor.execute(statement)
                    if table_name:
                        created.append(table_name)
                except Exception as exc:
                    if "already exists" in str(exc).lower():
                        skipped.append(table_name or "index/metadata")
                        continue
                    raise
            connection.commit()
    except AccessDatabaseInitializationError:
        raise
    except Exception as exc:
        raise AccessDatabaseInitializationError(f"Access schema initialization failed for {db_path}: {exc}") from exc
    return {"database": str(db_path), "created": created, "skipped": skipped, "ok": True}
