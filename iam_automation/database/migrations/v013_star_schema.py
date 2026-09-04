"""Compatibility label for the star-schema migration."""

VERSION = "v013_star_schema"
DESCRIPTION = "Create relational dimensions and facts for the clean-start testing runtime."


def upgrade(connection) -> None:
    return None
