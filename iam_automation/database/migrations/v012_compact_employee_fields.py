"""Compatibility label for the compact employee field migration."""

VERSION = "v012_compact_employee_fields"
DESCRIPTION = "Add governed current employee field projections without removing historical evidence."


def upgrade(connection) -> None:
    return None
