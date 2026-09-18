"""Abstract contract for rules executed around source ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def _contract_value(value: object) -> bool:
    """Return whether a result detail is safe to cross the rule boundary."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_contract_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _contract_value(item)
            for key, item in value.items()
        )
    return False


class RulePhase(str, Enum):
    """The point in the ingestion lifecycle where a rule is evaluated."""

    BEFORE = "BEFORE"
    AFTER = "AFTER"


@dataclass(frozen=True)
class RuleContext:
    """Stable input passed to every pipeline rule.

    ``batch_id`` is populated after the ingestion service has staged normalized
    evidence. A ``BEFORE`` rule queries that staged batch before ``AFTER``
    rules publish findings; it does not receive an adapter result or parse
    source files.
    """

    phase: RulePhase
    database_path: Path
    actor: str = "system"
    batch_id: str | None = None
    before_rule_results: tuple[RuleResult, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.before_rule_results, tuple) or not all(
            isinstance(result, RuleResult) for result in self.before_rule_results
        ):
            raise TypeError("RuleContext.before_rule_results must be RuleResult values.")


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

    def __post_init__(self) -> None:
        if not isinstance(self.details, Mapping) or not _contract_value(self.details):
            raise TypeError(
                "RuleResult.details must contain only JSON-like contract values."
            )

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

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def applies_to(self, context: RuleContext) -> bool:
        """Return whether this generic pipeline rule applies to the batch."""
        return True

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """Evaluate the rule for the current pipeline context."""
