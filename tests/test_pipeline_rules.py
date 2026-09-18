"""Tests for phase-aware pipeline rule discovery and orchestration."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from iam_automation.application.ingestion.orchestrator import IngestionOrchestrator
from iam_automation.application.rules import PipelineRule, RuleContext, RulePhase, RuleRegistry, RuleResult


@dataclass(frozen=True)
class _FakeResult:
    batch_id: str = "batch-1"


class _BeforeRule(PipelineRule):
    key = "test-before"
    phase = RulePhase.BEFORE
    calls: list[str] = []

    def evaluate(self, context: RuleContext) -> RuleResult:
        self.calls.append(f"before:{context.batch_id}")
        return RuleResult.success(self.key, self.phase)


class _AfterRule(PipelineRule):
    key = "test-after"
    phase = RulePhase.AFTER
    calls: list[str] = []

    def evaluate(self, context: RuleContext) -> RuleResult:
        self.calls.append(f"after:{context.batch_id}")
        return RuleResult.success(self.key, self.phase)


class _BlockingRule(PipelineRule):
    key = "test-blocking"
    phase = RulePhase.BEFORE

    def evaluate(self, context: RuleContext) -> RuleResult:
        return RuleResult.failure(self.key, self.phase, message="blocked", blocking=True)


class _FailingAfterRule(PipelineRule):
    key = "test-failing-after"
    phase = RulePhase.AFTER

    def evaluate(self, context: RuleContext) -> RuleResult:
        raise RuntimeError("after failed")


class PipelineRuleTests(unittest.TestCase):
    def test_discovery_includes_configured_after_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = RuleRegistry.discover(Path(tmp) / "runtime.sqlite")
            self.assertIn("configured-business-rules", {rule.key for rule in registry.rules(RulePhase.AFTER)})

    def test_orchestrator_runs_before_then_after_and_preserves_adapter_result(self):
        _BeforeRule.calls.clear()
        _AfterRule.calls.clear()
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "runtime.sqlite"
            registry = RuleRegistry((_AfterRule(database), _BeforeRule(database)))
            orchestrator = IngestionOrchestrator(database, rule_registry=registry)

            class Adapter:
                def ingest_file(self, path: Path, actor: str = "") -> _FakeResult:
                    return _FakeResult()

            orchestrator._factories["TEST"] = lambda: Adapter()
            result = orchestrator.ingest_file("TEST", Path(tmp) / "source.xlsx", actor="tester")

            self.assertEqual(result.batch_id, "batch-1")
            self.assertEqual(_BeforeRule.calls, ["before:batch-1"])
            self.assertEqual(_AfterRule.calls, ["after:batch-1"])
            self.assertEqual([item.phase for item in orchestrator.last_rule_results], [RulePhase.BEFORE, RulePhase.AFTER])

    def test_before_rule_never_blocks_adapter_execution_in_phase_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "runtime.sqlite"
            orchestrator = IngestionOrchestrator(database, rule_registry=RuleRegistry((_BlockingRule(database),)))
            called = []

            class Adapter:
                def ingest_file(self, path: Path, actor: str = "") -> _FakeResult:
                    called.append(True)
                    return _FakeResult()

            orchestrator._factories["TEST"] = lambda: Adapter()
            result = orchestrator.ingest_file("TEST", Path(tmp) / "source.xlsx")
            self.assertEqual(result.batch_id, "batch-1")
            self.assertEqual(called, [True])
            self.assertFalse(orchestrator.last_before_rule_results[0].passed)

    def test_after_rule_failure_is_returned_without_undoing_adapter_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "runtime.sqlite"
            registry = RuleRegistry((_FailingAfterRule(database),))
            orchestrator = IngestionOrchestrator(database, rule_registry=registry)

            class Adapter:
                def ingest_file(self, path: Path, actor: str = "") -> _FakeResult:
                    return _FakeResult()

            orchestrator._factories["TEST"] = lambda: Adapter()
            result = orchestrator.ingest_file("TEST", Path(tmp) / "source.xlsx")

            self.assertEqual(result.batch_id, "batch-1")
            self.assertFalse(orchestrator.last_after_rule_results[0].passed)
            self.assertEqual(orchestrator.last_after_rule_results[0].details["exception"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
