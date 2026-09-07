"""Shared application contracts and utilities for source ingestion.

Source-specific adapters remain responsible for reading and normalizing their
own files.  This package contains the small pieces that must be consistent
across every source while the adapters are migrated incrementally.
"""

from .contracts import IngestionResult, quarantine_count

__all__ = ["IngestionResult", "quarantine_count"]
