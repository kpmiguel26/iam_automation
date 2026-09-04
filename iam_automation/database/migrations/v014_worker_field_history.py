"""Compatibility label for the worker field history migration."""

VERSION = "v014_worker_field_history"
DESCRIPTION = "Store legacy worker profile history as relational field values."


def upgrade(connection) -> None:
    return None
