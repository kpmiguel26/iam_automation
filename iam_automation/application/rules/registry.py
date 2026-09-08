"""Rule discovery and phase-aware execution."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Iterable

from .base import PipelineRule, RuleContext, RulePhase, RuleResult

logger = logging.getLogger(__name__)


def _rule_classes() -> list[type[PipelineRule]]:
    classes: list[type[PipelineRule]] = []
    pending = list(PipelineRule.__subclasses__())
    while pending:
        candidate = pending.pop(0)
        pending.extend(candidate.__subclasses__())
        if not inspect.isabstract(candidate) and candidate not in classes:
            classes.append(candidate)
    return classes


class RuleRegistry:
    """Own the discovered rule set and execute one phase at a time."""

    def __init__(self, rules: Iterable[PipelineRule] = ()):
        self._rules = tuple(rules)
        keys: set[tuple[str, RulePhase]] = set()
        for rule in self._rules:
            key = (str(rule.key), rule.phase)
            if key in keys:
                raise ValueError(f"Duplicate pipeline rule: {rule.key} ({rule.phase.value}).")
            keys.add(key)

    @classmethod
    def discover(cls, database_path: Path, package_name: str = "iam_automation.application.rules") -> "RuleRegistry":
        """Import rule modules and instantiate every concrete rule class."""
        package = importlib.import_module(package_name)
        for module in pkgutil.iter_modules(package.__path__, f"{package_name}."):
            if module.name.rsplit(".", 1)[-1] in {"base", "registry"}:
                continue
            importlib.import_module(module.name)
        instances = []
        for rule_class in _rule_classes():
            key = getattr(rule_class, "key", "")
            phase = getattr(rule_class, "phase", None)
            if not key or not isinstance(phase, RulePhase):
                raise TypeError(f"Pipeline rule {rule_class.__name__} must define key and phase.")
            if not rule_class.__module__.startswith(f"{package_name}."):
                continue
            instances.append(rule_class(database_path))
        return cls(instances)

    def rules(self, phase: RulePhase | None = None) -> tuple[PipelineRule, ...]:
        if phase is None:
            return self._rules
        return tuple(rule for rule in self._rules if rule.phase == phase)

    def run(self, context: RuleContext) -> tuple[RuleResult, ...]:
        """Run applicable rules for a phase in deterministic key order."""
        results: list[RuleResult] = []
        for rule in sorted(self.rules(context.phase), key=lambda item: item.key):
            if not rule.applies_to(context):
                continue
            try:
                result = rule.evaluate(context)
            except Exception as exc:
                logger.exception("Pipeline rule failed during %s: %s", context.phase.value, rule.key)
                result = RuleResult.failure(rule.key, context.phase, message=str(exc), details={"exception": type(exc).__name__})
            if result.rule_key != rule.key or result.phase != context.phase:
                raise TypeError(f"Pipeline rule {rule.key} returned an invalid result.")
            results.append(result)
            # Phase one is evidence collection only. A failed BEFORE result
            # must not prevent the source adapter from persisting evidence.
            # Quarantine disposition belongs to the fact/read model.
        return tuple(results)
