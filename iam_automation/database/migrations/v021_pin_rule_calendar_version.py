"""Compatibility label for pinning rule contexts to calendar versions."""

VERSION = "v021_pin_rule_calendar_version"
DESCRIPTION = "Pin each rule context version to an immutable calendar version."


def upgrade(connection) -> None:
    return None
