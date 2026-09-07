"""Contracts shared by source ingestion application services."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IngestionResult(Protocol):
    """Minimal result returned after a source has been staged.

    Source adapters may expose a concrete frozen dataclass with additional
    fields.  Keeping this protocol structural lets the watcher coordinate all
    adapters without importing their implementation details.
    """

    batch_id: str
    filename: str
    total_rows: int
    staged_rows: int
    already_processed: bool


def quarantine_count(result: object) -> int:
    """Read the quarantine count across the legacy result spellings.

    ``RsrIngestionResult`` historically called this field
    ``quarantined_rows`` while the application services use
    ``quarantine_rows``.  The compatibility boundary belongs here so new
    orchestration code can use one name while adapters are migrated.
    """

    value = getattr(result, "quarantine_rows", None)
    if value is None:
        value = getattr(result, "quarantined_rows", 0)
    return max(0, int(value or 0))
