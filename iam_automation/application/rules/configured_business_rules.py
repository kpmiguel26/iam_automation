"""Bridge the existing SQLite-configured rules into the pipeline."""

from __future__ import annotations

from .base import PipelineRule, RuleContext, RulePhase, RuleResult
from .service import BusinessRuleService
from ...domain.rules.calendar import CalendarConfigurationRequired


class ConfiguredBusinessRulesBeforeImport(PipelineRule):
    """Evaluate configured BEFORE rules against a staged database batch."""

    key = "configured-business-rules-before"
    phase = RulePhase.BEFORE

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not context.batch_id:
            return RuleResult.success(self.key, self.phase, message="No staged import batch was produced for preflight evaluation.")
        try:
            details = BusinessRuleService(self.database_path).preflight_batch(context.batch_id)
        except CalendarConfigurationRequired as exc:
            return RuleResult.failure(
                self.key,
                self.phase,
                message=str(exc),
                details={"calendar_configuration_required": True},
            )
        matches = details.get("matches", [])
        result_type = RuleResult.failure if matches else RuleResult.success
        return result_type(
            self.key,
            self.phase,
            message=(f"{len(matches)} BEFORE rule match(es) found." if matches else "No BEFORE rule matches found."),
            details=details,
        )


class ConfiguredBusinessRulesAfterImport(PipelineRule):
    """Persist BEFORE matches and evaluate AFTER rules after a batch commits."""

    key = "configured-business-rules"
    phase = RulePhase.AFTER

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not context.batch_id:
            return RuleResult.success(self.key, self.phase, message="No import batch was produced.")
        service = BusinessRuleService(self.database_path)
        try:
            before_created = service.persist_before_findings(context.batch_id, context.before_rule_results)
            after_created = service.evaluate_batch(context.batch_id)
        except CalendarConfigurationRequired as exc:
            return RuleResult.failure(
                self.key,
                self.phase,
                message=str(exc),
                details={"batch_id": context.batch_id, "calendar_configuration_required": True},
            )
        return RuleResult.success(
            self.key,
            self.phase,
            message="Configured BEFORE and AFTER business rules evaluated without blocking import.",
            details={
                "batch_id": context.batch_id,
                "before_findings_created": before_created,
                "after_findings_created": after_created,
                "findings_created": before_created + after_created,
            },
        )
