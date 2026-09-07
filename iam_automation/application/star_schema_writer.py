"""Compatibility facade for the SQLite star-schema writer.

New ingestion code should import the persistence component from
``infrastructure.sqlite.star_schema_writer``. This module remains available
for existing application and extension imports during the transition.
"""

from ..infrastructure.sqlite.star_schema_writer import StarSchemaWriter

__all__ = ["StarSchemaWriter"]
