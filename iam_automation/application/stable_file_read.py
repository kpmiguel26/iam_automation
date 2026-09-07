"""Compatibility facade for the shared ingestion filesystem helpers.

Keep this import path for callers outside the ingestion package while source
adapters migrate to :mod:`application.ingestion.common`.
"""

from .ingestion.common import file_modified_at_utc, read_stable_bytes

__all__ = ["file_modified_at_utc", "read_stable_bytes"]
#endfile
