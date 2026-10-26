"""Immutable contracts for the isolated parallel ingestion runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceTemplate:
    source_id: str
    version_id: str
    version_number: int
    display_name: str
    definition: dict[str, Any]
    watched_path: Path
    ingestion_order: int


@dataclass(frozen=True)
class ObjectTemplate:
    version_id: str
    version_number: int
    definition: dict[str, Any]
    approved_by: str
    approved_at_utc: str
    sources: tuple[SourceTemplate, ...]


@dataclass(frozen=True)
class RuntimeConfiguration:
    object_template: ObjectTemplate
    sources: tuple[SourceTemplate, ...]


@dataclass(frozen=True)
class FileRecognitionAnalysis:
    """Persistable, non-row-level result of checking a file against one template."""

    source: SourceTemplate
    recognition_status: str
    worksheet_name: str
    detected_headers: tuple[str, ...]
    required_headers: tuple[str, ...]
    missing_headers: tuple[str, ...]
    unknown_headers: tuple[str, ...]
    checks: dict[str, Any]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedSourceRow:
    row_number: int
    sheet_name: str
    raw_values: dict[str, Any]
    normalized_values: dict[str, Any]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineRunResult:
    batch_id: str
    source_id: str
    source_version_id: str
    object_template_version_id: str
    file_path: str
    file_checksum: str
    status: str
    total_rows: int
    evidence_rows: int
    quarantined_rows: int
    objects_created: int
    objects_linked: int
    message: str = ""


class TemplateConfigurationError(ValueError):
    """A persisted configuration cannot safely be executed by runtime v2."""


class SourceRecognitionError(ValueError):
    """A file cannot be uniquely assigned to one configured source."""
