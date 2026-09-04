"""Compatibility label for the Alembic business-rules migration."""

VERSION = "v011_business_rules"
DESCRIPTION = "Register post-import business rule definitions and findings."


def upgrade(connection) -> None:
    return None
