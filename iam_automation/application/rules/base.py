"""Abstract contract for rules executed around source ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class RulePhase(str, Enum):
    """The point in the ingestion lifecycle where a rule is evaluated."""

    BEFORE = "BEFORE"
    AFTER = "AFTER"


@dataclass(frozen=True)
class RuleContext:
    """Stable input passed to every pipeline rule.

    ``result`` and ``batch_id`` are populated for ``AFTER`` rules.  A before
    rule can inspect the source path and metadata without depending on an
    adapter implementation.
    """

    phase: RulePhase
    source_system: str
    database_path: Path
    path: Path | None = None
    actor: str = "system"
    batch_id: str | None = None
    result: object | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleResult:
    """Outcome returned by a pipeline rule.

    Pipeline rule results are advisory in phase one. ``BEFORE`` and ``AFTER``
    failures are reported to the orchestrator and never block or undo an
    import. The ``blocking`` field is retained for compatibility with the
    original contract and future policy decisions.
    """

    rule_key: str
    phase: RulePhase
    passed: bool = True
    blocking: bool = False
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, rule_key: str, phase: RulePhase, *, message: str = "", details: Mapping[str, Any] | None = None) -> "RuleResult":
        return cls(rule_key, phase, True, False, message, details or {})

    @classmethod
    def failure(cls, rule_key: str, phase: RulePhase, *, message: str, blocking: bool = False, details: Mapping[str, Any] | None = None) -> "RuleResult":
        return cls(rule_key, phase, False, blocking, message, details or {})


class RuleExecutionError(RuntimeError):
    """Compatibility exception retained for callers of the old contract."""

    def __init__(self, result: RuleResult):
        self.result = result
        super().__init__(result.message or f"Pipeline rule {result.rule_key} blocked ingestion.")


class PipelineRule(ABC):
    """Base class discovered and executed by ``IngestionOrchestrator``."""

    key: str
    phase: RulePhase
    source_systems: frozenset[str] = frozenset()

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def applies_to(self, context: RuleContext) -> bool:
        return not self.source_systems or context.source_system in self.source_systems

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """Evaluate the rule for the current pipeline context."""
