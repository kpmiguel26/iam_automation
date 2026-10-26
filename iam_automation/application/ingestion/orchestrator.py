"""Coordinate source-specific ingestion adapters.

The orchestrator owns adapter selection and the lifecycle boundary for
pipeline rules.  It deliberately does not own parsing, matching or
promotion; those concerns remain in the source adapters and application
services.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter
from ..accessnow_ingestion_service import AccessNowIngestionService
from ..master_roster_ingestion_service import MasterRosterIngestionService
from ..roster_lock_ingestion_service import RosterLockIngestionService
from ..rules import RuleContext, RulePhase, RuleRegistry, RuleResult


class IngestionOrchestrator:
    """Dispatch a source file to the adapter responsible for its format.

    DEPRECATED (migration in progress): runtime v2 now recognizes configured
    report files from approved template snapshots, overlapping the source
    selection responsibility here. This facade still dispatches imports to
    legacy adapters and runs their Rules Engine lifecycle; keep it active until
    v2 has physical-model writes, rule parity, and source-by-source cutover.
    """

    FILE_SOURCES: frozenset[str] = frozenset(
        {
            "ROSTER_LOCK",
            "MASTER_ROSTER",
            "RSR_SUPPLIER_WORKER_DETAILS",
        }
    )

    def __init__(self, database_path: Path, rule_registry: RuleRegistry | None = None):
        self.database_path = database_path
        self.rule_registry = rule_registry or RuleRegistry.discover(database_path)
        self.last_rule_results: tuple[RuleResult, ...] = ()
        self.last_before_rule_results: tuple[RuleResult, ...] = ()
        self.last_after_rule_results: tuple[RuleResult, ...] = ()
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
            result = adapter.ingest_file(path)
        else:
            result = adapter.ingest_file(path, actor=actor)
        self._run_rules_after_staging(actor, str(getattr(result, "batch_id", "")) or None)
        return result

    def ingest_accessnow(self, folder: Path, *, actor: str = "workspace-watcher") -> Any:
        """Stage the AccessNow active and termination reports as one view."""
        result = AccessNowIngestionService(self.database_path).ingest_folder(folder)
        self._run_rules_after_staging(actor, str(getattr(result, "batch_id", "")) or None)
        return result

    def _run_rules_after_staging(self, actor: str, batch_id: str | None) -> None:
        self.last_before_rule_results = self.rule_registry.run(
            RuleContext(
                phase=RulePhase.BEFORE,
                database_path=self.database_path,
                actor=actor,
                batch_id=batch_id,
            )
        )
        self.last_after_rule_results = self.rule_registry.run(
            RuleContext(
                phase=RulePhase.AFTER,
                database_path=self.database_path,
                actor=actor,
                batch_id=batch_id,
                before_rule_results=self.last_before_rule_results,
            )
        )
        self.last_rule_results = self.last_before_rule_results + self.last_after_rule_results
