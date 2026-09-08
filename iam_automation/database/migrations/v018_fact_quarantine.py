"""Compatibility label for the master quarantine fact migration."""

VERSION = "v018_fact_quarantine"
DESCRIPTION = "Store rule violations as a star-schema quarantine fact."


def upgrade(connection) -> None:
    return None
