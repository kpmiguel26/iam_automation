"""Contracts shared by source ingestion application services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FieldMapping:
    """Governed mapping produced with a staged ingestion batch."""

    mapping_id: str
    source_field_key: str
    field_id: str | None
    field_key: str | None
    target_kind: str
    transform_name: str
    mapping_version: int
    active: bool = True


@dataclass(frozen=True)
class RecordMetadata:
    """Lineage metadata that is safe to expose across engines."""

    source_record_key: str = ""
    row_number: int = 0
    status: str = ""


@dataclass(frozen=True)
class BatchMetadata:
    """Small, typed batch metadata contract; no arbitrary key/value bag."""

    record_count: int = 0
    schema_version: str = "1"


@dataclass(frozen=True)
class NormalizedRecord:
    """Source-neutral normalized record consumed by downstream engines."""

    record_id: str
    source_id: str
    fields: dict[str, Any]
    metadata: RecordMetadata = field(default_factory=RecordMetadata)


@dataclass(frozen=True)
class IngestionBatch:
    """Minimal hand-off from ingestion staging to downstream consumers.

    The contract intentionally contains no file path, report name, reader,
    normalizer or adapter type. Those concerns belong to the producer.
    """

    batch_id: str
    source_id: str
    status: str
    records: tuple[NormalizedRecord, ...] = ()
    field_mappings: tuple[FieldMapping, ...] = ()
    metadata: BatchMetadata = field(default_factory=BatchMetadata)


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
