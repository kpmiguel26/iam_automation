"""Compatibility label for binding rule versions to context versions."""

VERSION = "v020_rule_context_binding"
DESCRIPTION = "Bind each rule version to the context used for evaluation."


def upgrade(connection) -> None:
    return None
