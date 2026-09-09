"""Compatibility label for versioned rule context and field metadata."""

VERSION = "v019_rule_configuration"
DESCRIPTION = "Add versioned calendars, rule context settings and governed field metadata."


def upgrade(connection) -> None:
    return None
