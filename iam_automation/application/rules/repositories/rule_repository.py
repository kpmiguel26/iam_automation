"""SQLite persistence boundary for configured business rules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from ....infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    FactQuarantineModel,
    RuleFindingModel,
)


class RuleRepository:
    """Persist rule definitions without owning rule configuration or evaluation."""

    @staticmethod
    def list_with_current_versions(session: Any) -> tuple[tuple[BusinessRuleModel, BusinessRuleVersionModel | None], ...]:
        rules = session.scalars(
            select(BusinessRuleModel).order_by(BusinessRuleModel.name.asc())
        ).all()
        return tuple(
            (
                rule,
                session.scalar(select(BusinessRuleVersionModel).where(
                    BusinessRuleVersionModel.rule_id == rule.rule_id,
                    BusinessRuleVersionModel.version == rule.current_version,
                )),
            )
            for rule in rules
        )

    @staticmethod
    def add_versioned_rule(
        session: Any,
        *,
        rule_id: str,
        name: str,
        description: str,
        rule_type: str,
        phase: str,
        context_version_id: str | None,
        condition_json: str,
        scope_json: str,
        severity: str,
        actor: str,
        created_at_utc: str,
    ) -> None:
        session.add(BusinessRuleModel(
            rule_id=rule_id,
            name=name,
            description=description,
            rule_type=rule_type,
            status="DRAFT",
            current_version=1,
            created_by=actor,
            created_at_utc=created_at_utc,
            updated_at_utc=created_at_utc,
        ))
        session.add(BusinessRuleVersionModel(
            rule_version_id=f"{rule_id}:1",
            rule_id=rule_id,
            version=1,
            phase=phase,
            context_version_id=context_version_id,
            condition_json=condition_json,
            scope_json=scope_json,
            severity=severity,
            status="DRAFT",
            created_by=actor,
            created_at_utc=created_at_utc,
        ))

    @staticmethod
    def set_status(session: Any, rule_id: str, status: str) -> None:
        rule = session.get(BusinessRuleModel, rule_id)
        if rule is None:
            raise ValueError("Rule not found.")
        rule.status = status
        version = session.scalar(select(BusinessRuleVersionModel).where(
            BusinessRuleVersionModel.rule_id == rule_id,
            BusinessRuleVersionModel.version == rule.current_version,
        ))
        if version is not None:
            version.status = status

    @staticmethod
    def delete(session: Any, rule_id: str) -> dict[str, int]:
        rule = session.get(BusinessRuleModel, rule_id)
        if rule is None:
            raise ValueError("Rule not found.")
        fact_result = session.execute(
            delete(FactQuarantineModel).where(FactQuarantineModel.rule_id == rule_id)
        )
        finding_result = session.execute(
            delete(RuleFindingModel).where(RuleFindingModel.rule_id == rule_id)
        )
        version_result = session.execute(
            delete(BusinessRuleVersionModel).where(BusinessRuleVersionModel.rule_id == rule_id)
        )
        session.delete(rule)
        return {
            "rule": 1,
            "versions": int(version_result.rowcount or 0),
            "findings": int(finding_result.rowcount or 0),
            "quarantine_facts": int(fact_result.rowcount or 0),
        }
