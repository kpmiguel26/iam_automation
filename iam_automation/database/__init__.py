"""Microsoft Access master snapshot and database schema boundary."""

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
