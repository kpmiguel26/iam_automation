"""Coordinate source-specific ingestion adapters.

The orchestrator owns adapter selection.  It deliberately does not own
parsing, matching, promotion, or business-rule evaluation; those concerns
remain in their existing components while ingestion is migrated incrementally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter
from ..accessnow_ingestion_service import AccessNowIngestionService
from ..master_roster_ingestion_service import MasterRosterIngestionService
from ..roster_lock_ingestion_service import RosterLockIngestionService


class IngestionOrchestrator:
    """Dispatch a source file to the adapter responsible for its format."""

    FILE_SOURCES: frozenset[str] = frozenset(
        {
            "ROSTER_LOCK",
            "MASTER_ROSTER",
            "RSR_SUPPLIER_WORKER_DETAILS",
        }
    )

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._factories: dict[str, Callable[[], Any]] = {
            "ROSTER_LOCK": lambda: RosterLockIngestionService(database_path),
            "MASTER_ROSTER": lambda: MasterRosterIngestionService(database_path),
            "RSR_SUPPLIER_WORKER_DETAILS": lambda: RsrSupplierWorkerDetailsAdapter(database_path),
        }

    def ingest_file(self, source_system: str, path: Path, *, actor: str = "workspace-watcher") -> Any:
        """Stage one file through the adapter registered for its source."""
        normalized_source = str(source_system).strip().upper()
        factory = self._factories.get(normalized_source)
        if factory is None:
            raise ValueError(f"No file ingestion adapter is registered for {source_system!r}.")
        adapter = factory()
        if normalized_source == "ROSTER_LOCK":
            return adapter.ingest_file(path)
        return adapter.ingest_file(path, actor=actor)

    def ingest_accessnow(self, folder: Path) -> Any:
        """Stage the AccessNow active and termination reports as one view."""
        return AccessNowIngestionService(self.database_path).ingest_folder(folder)
