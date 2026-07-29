"""Baseline for the schema created by runtime_schema.initialize_runtime_database."""


VERSION = "v001_initial_schema"
DESCRIPTION = "Register the existing runtime schema as the migration baseline."


def upgrade(connection) -> None:
    # The bootstrap schema already creates the initial tables. This migration
    # records that state so future changes can be applied incrementally.
    return None
