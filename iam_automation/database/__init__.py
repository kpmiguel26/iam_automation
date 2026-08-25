"""
File: iam_automation/database/__init__.py
Purpose: Microsoft Access master snapshot and database schema boundary.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: initializer, runtime_schema, migration_runner, schema
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from .initializer import AccessDatabaseInitializationError, initialize_access_database
from .runtime_schema import RUNTIME_SCHEMA_VERSION, initialize_runtime_database
from .migration_runner import applied_migrations, apply_pending_migrations
from .schema import ACCESS_SCHEMA_VERSION, ACCESS_TABLES, access_schema_statements

__all__ = [
    "ACCESS_SCHEMA_VERSION",
    "ACCESS_TABLES",
    "AccessDatabaseInitializationError",
    "RUNTIME_SCHEMA_VERSION",
    "access_schema_statements",
    "initialize_access_database",
    "initialize_runtime_database",
    "applied_migrations",
    "apply_pending_migrations",
]
#endfile
