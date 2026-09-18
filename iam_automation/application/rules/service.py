"""Evaluate advisory business rules against persisted source evidence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..business_calendar import configured_rule_calendar
from ..condition_evaluator import ConditionEvaluator, ConditionValidationError
from .catalog import RuleCatalogRepository
from .evidence import SqliteEvidenceRepository
from .execution import RuleExecutionService
from .repositories import FindingRepository, QuarantineRepository, RuleRepository
from ...infrastructure.sqlite.orm import (
    RuleFindingModel,
    RuleContextVersionModel,
    RuleContextModel,
    orm_session,
)


class BusinessRuleService:
    """Phase-one rule engine: findings only, never an import gate."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._catalog = RuleCatalogRepository()
        self._rules = RuleRepository()
        self._findings = FindingRepository()
        self._quarantine = QuarantineRepository()
        self._evidence_repository = SqliteEvidenceRepository()
        self._execution = RuleExecutionService(self, self._evidence_repository)

    ALLOWED_OPERATORS = ("exists", "missing", "equals", "not_equals", "contains", "in")
    ALLOWED_SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
    ALLOWED_PHASES = ("BEFORE", "AFTER")
    OPERATOR_LABELS = {
        "exists": "is present",
        "missing": "is missing",
        "equals": "equals",
        "not_equals": "does not equal",
        "contains": "contains",
        "in": "is one of",
        "greater_than": "is greater than",
        "less_than": "is less than",
        "between": "is between",
        "before": "is before",
        "after": "is after",
    }
    OPERATOR_DESCRIPTIONS = {
        "exists": "Find rows where this data has been provided.",
        "missing": "Find rows where this data has not been provided.",
        "equals": "Find rows whose value matches exactly.",
        "not_equals": "Find rows whose value is different.",
        "contains": "Find rows where the value includes some text.",
        "in": "Find rows whose value matches one of several options.",
        "greater_than": "Find values greater than the comparison value.",
        "less_than": "Find values less than the comparison value.",
        "between": "Find values inside an inclusive range.",
        "before": "Find dates before the comparison date.",
        "after": "Find dates after the comparison date.",
    }
    SEVERITY_LABELS = {
        "INFO": "Informational",
        "WARNING": "Needs review",
        "ERROR": "Important review",
        "CRITICAL": "Urgent review",
    }
    PHASE_LABELS = {"BEFORE": "Before import", "AFTER": "After import"}
    PHASE_DESCRIPTIONS = {
        "BEFORE": "Checks staged evidence before AFTER evaluation.",
        "AFTER": "Checks the saved records after the import completes.",
    }
    STATUS_LABELS = {"ACTIVE": "Enabled", "DRAFT": "Draft", "DISABLED": "Disabled"}

    def list_rules(self) -> list[dict]:
        with orm_session(self.database_path) as session:
            result = []
            for rule, version in self._rules.list_with_current_versions(session):
                scope = self._json(version.scope_json) if version is not None else {}
                condition = self._runtime_condition(self._json(version.condition_json), session) if version is not None else {}
                source_system = self._catalog.source_system(session, scope.get("source_id")) if scope.get("source_id") else None
                source_system = str(source_system or scope.get("source_system") or "ALL")
                phase = str(version.phase or "AFTER") if version is not None else "AFTER"
                severity = str(version.severity or "WARNING") if version is not None else "WARNING"
                result.append({"rule": rule, "version": version, "execution_phase": phase, "source_system": source_system, "source_label": "All reports" if source_system == "ALL" else self._catalog.source_label(session, source_system)})
                result[-1].update({
                    "condition": condition,
                    "field_label": self._humanize_field(condition.get("field")),
                    "condition_display": self._condition_display(condition),
                    "phase_label": self.PHASE_LABELS.get(phase, phase.title()),
                    "phase_description": self.PHASE_DESCRIPTIONS.get(phase, "Runs during the import workflow."),
                    "severity_label": self.SEVERITY_LABELS.get(severity, severity.title()),
                    "status_label": self.STATUS_LABELS.get(str(rule.status), str(rule.status).title()),
                    "response_display": "Creates a review item without blocking the import.",
                })
            return result

    @staticmethod
    def _humanize_field(field: object) -> str:
        """Turn a canonical field key into a label suitable for end users."""
        words = []
        acronyms = {"id": "ID", "nuid": "NUID", "npn": "NPN", "rsr": "RSR", "hr": "HR", "url": "URL"}
        for word in str(field or "").replace("_", " ").split():
            words.append(acronyms.get(word.casefold(), word.capitalize()))
        return " ".join(words) or "This field"

    @classmethod
    def _condition_display(cls, condition: dict) -> str:
        if "all" in condition:
            return " AND ".join(cls._condition_display(item) for item in condition.get("all", []))
        if "any" in condition:
            return " OR ".join(cls._condition_display(item) for item in condition.get("any", []))
        if "not" in condition:
            return f"NOT ({cls._condition_display(condition.get('not') or {})})"
        if "left" in condition:
            left = cls._operand_display(condition.get("left"))
            right = cls._operand_display(condition.get("right"))
            operator = str(condition.get("operator") or "").casefold()
            return f"{left} {cls.OPERATOR_LABELS.get(operator, operator)} {right}".strip()
        field_label = cls._humanize_field(condition.get("field"))
        operator = str(condition.get("operator") or "").casefold()
        if operator in {"exists", "missing"}:
            return f"{field_label} {cls.OPERATOR_LABELS.get(operator, operator)}"
        value = condition.get("value", "")
        if isinstance(value, list):
            value_text = ", ".join(str(item) for item in value)
        else:
            value_text = str(value or "")
        return f"{field_label} {cls.OPERATOR_LABELS.get(operator, operator)} '{value_text}'"

    @classmethod
    def _operand_display(cls, operand: object) -> str:
        if not isinstance(operand, dict):
            return "value"
        kind = str(operand.get("kind") or "").casefold()
        if kind == "field":
            source = str(operand.get("source") or "").strip()
            field = cls._humanize_field(operand.get("field"))
            return f"{source} / {field}" if source else field
        if kind == "derived":
            return str(operand.get("function") or "derived value").replace("_", " ")
        value = operand.get("value", "")
        if isinstance(value, list):
            return "[" + ", ".join(str(item) for item in value) + "]"
        return f"'{value}'"

    @classmethod
    def operator_options(cls) -> tuple[dict[str, str], ...]:
        """Return user-facing operator choices for the guided rule builder."""
        return tuple(
            {
                "key": operator,
                "label": cls.OPERATOR_LABELS.get(operator, operator.title()),
                "description": cls.OPERATOR_DESCRIPTIONS.get(operator, "Review this condition."),
            }
            for operator in cls.ALLOWED_OPERATORS
        )

    def available_field_options(self, source_system: str = "ALL") -> tuple[dict[str, str], ...]:
        """Return canonical field keys with readable labels for the wizard."""
        return tuple(
            {"key": field, "label": self._humanize_field(field)}
            for field in self.available_fields(source_system)
        )

    def available_sources(self) -> tuple[dict[str, str], ...]:
        with orm_session(self.database_path) as session:
            sources = self._catalog.sources(session)
            return (
                {"key": "ALL", "label": "All reports", "description": "Evaluate the rule against every source."},
                *tuple(
                    {"key": source.source_system, "label": source.label or source.source_system, "description": f"Only fields from {source.label or source.source_system}."}
                    for source in sources
                ),
            )

    def available_condition_fields(self) -> tuple[dict[str, str], ...]:
        """Return field choices annotated with their governed source."""
        with orm_session(self.database_path) as session:
            return self._catalog.condition_fields(session)

    def _configured_source_keys(self) -> frozenset[str]:
        with orm_session(self.database_path) as session:
            return self._catalog.source_keys(session)

    @staticmethod
    def condition_from_form(values) -> dict:
        """Build the explicit condition tree from the guided editor fields."""
        def get_list(name: str) -> list[str]:
            return [str(item or "").strip() for item in values.getlist(name)]

        def operand(prefix: str, index: int) -> dict:
            kind = get_list(f"{prefix}_kind")[index]
            if kind == "field":
                return {"kind": "field", "source": get_list(f"{prefix}_source")[index], "field": get_list(f"{prefix}_field")[index]}
            if kind == "derived":
                arguments = []
                for argument in ("arg1", "arg2"):
                    argument_kind = get_list(f"{prefix}_{argument}_kind")[index]
                    if argument_kind == "field":
                        arguments.append({"kind": "field", "source": get_list(f"{prefix}_{argument}_source")[index], "field": get_list(f"{prefix}_{argument}_field")[index]})
                    else:
                        arguments.append({"kind": "literal", "value": get_list(f"{prefix}_{argument}_value")[index]})
                return {"kind": "derived", "function": get_list(f"{prefix}_function")[index], "arguments": arguments}
            return {"kind": "literal", "value": get_list(f"{prefix}_value")[index]}

        group = str(values.get("condition_group") or "all").strip().lower()
        if group not in {"all", "any"}:
            raise ValueError("Choose whether all or any conditions must match.")
        operators = get_list("condition_operator")
        rows = []
        for index, operator in enumerate(operators):
            if not operator:
                continue
            left = operand("condition_left", index)
            right = operand("condition_right", index)
            if right.get("kind") == "literal" and operator in {"in", "between"}:
                right["value"] = [item.strip() for item in str(right.get("value") or "").split(",") if item.strip()]
                if operator == "between" and len(right["value"]) != 2:
                    raise ValueError("Between needs two values: enter a minimum and a maximum separated by a comma.")
            rows.append({"left": left, "operator": operator, "right": right})
        if not rows:
            raise ValueError("Add at least one comparison to the condition.")
        return {group: rows}

    def available_fields(self, source_system: str = "ALL") -> tuple[str, ...]:
        """Return known source fields for the guided rule builder."""
        with orm_session(self.database_path) as session:
            return self._catalog.fields(session, source_system)

    def create_rule(self, *, name: str, description: str, field: str, operator: str, value: str, severity: str, actor: str, phase: str = "AFTER", source_system: str = "ALL") -> str:
        name, field, operator, severity, phase, source_system = name.strip(), field.strip(), operator.strip(), severity.strip().upper(), phase.strip().upper(), source_system.strip().upper() or "ALL"
        configured_sources = self._configured_source_keys()
        if not name or not field or operator not in self.ALLOWED_OPERATORS or severity not in self.ALLOWED_SEVERITIES or phase not in self.ALLOWED_PHASES or source_system not in {"ALL", *configured_sources} or field not in set(self.available_fields(source_system)) or (operator in {"equals", "not_equals", "contains", "in"} and not value):
            raise ValueError("Name, phase, field, valid operator and severity are required.")
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        condition = {"field": field, "operator": operator}
        if operator in {"equals", "not_equals", "contains"}: condition["value"] = value
        if operator == "in": condition["value"] = [item.strip() for item in value.split(",") if item.strip()]
        with orm_session(self.database_path) as session:
            condition = self._catalog_condition(condition, session, source_system)
            source_id = self._catalog.source_id(session, source_system) if source_system != "ALL" else None
            scope = {} if source_system == "ALL" else {"source_id": source_id, "source_system": source_system}
            context_version_id = self._current_context_version_id(session)
            self._rules.add_versioned_rule(
                session,
                rule_id=rule_id,
                name=name,
                description=description.strip(),
                rule_type="RECORD_CONDITION",
                phase=phase,
                context_version_id=context_version_id,
                condition_json=json.dumps(condition, sort_keys=True),
                scope_json=json.dumps(scope, sort_keys=True),
                severity=severity,
                actor=actor,
                created_at_utc=now,
            )
        return rule_id

    def create_complex_rule(
        self,
        *,
        name: str,
        description: str,
        condition: dict,
        severity: str,
        actor: str,
        phase: str = "AFTER",
        source_system: str = "ALL",
    ) -> str:
        """Create a rule using the explicit left/operator/right language.

        The guided builder can continue using :meth:`create_rule` while more
        advanced builders compose conditions with ``all``/``any`` and derived
        operands. Both forms persist in the same versioned rule contract.
        """
        name = str(name or "").strip()
        description = str(description or "").strip()
        severity = str(severity or "").strip().upper()
        phase = str(phase or "").strip().upper()
        source_system = str(source_system or "ALL").strip().upper()
        if not name or severity not in self.ALLOWED_SEVERITIES or phase not in self.ALLOWED_PHASES:
            raise ValueError("Name, phase and severity are required.")
        if source_system not in {"ALL", *self._configured_source_keys()}:
            raise ValueError("Invalid rule report scope.")
        try:
            ConditionEvaluator().validate(condition)
            self._validate_condition_fields(condition, source_system)
        except ConditionValidationError as exc:
            raise ValueError(str(exc)) from exc
        except ValueError:
            raise
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            condition = self._catalog_condition(condition, session, source_system)
            source_id = self._catalog.source_id(session, source_system) if source_system != "ALL" else None
            scope = {} if source_system == "ALL" else {"source_id": source_id, "source_system": source_system}
            context_version_id = self._current_context_version_id(session)
            self._rules.add_versioned_rule(
                session,
                rule_id=rule_id,
                name=name,
                description=description,
                rule_type="COMPOSITE_CONDITION",
                phase=phase,
                context_version_id=context_version_id,
                condition_json=json.dumps(condition, sort_keys=True),
                scope_json=json.dumps(scope, sort_keys=True),
                severity=severity,
                actor=actor,
                created_at_utc=now,
            )
        return rule_id

    def _catalog_condition(self, condition: dict, session: Any, default_source: str = "ALL") -> dict:
        """Compatibility facade for catalog identity assignment."""
        return self._catalog.catalog_condition(condition, session, default_source)

    def _catalog_operand(self, operand: dict, session: Any, default_source: str) -> dict:
        """Compatibility facade for operand identity assignment."""
        return self._catalog.catalog_operand(operand, session, default_source)

    def _runtime_condition(self, condition: dict, session: Any) -> dict:
        """Compatibility facade for runtime catalog resolution."""
        return self._catalog.runtime_condition(condition, session)

    def _runtime_operand(self, operand: dict, session: Any) -> dict:
        """Compatibility facade for runtime operand resolution."""
        return self._catalog.runtime_operand(operand, session)

    def _validate_condition_fields(self, condition: dict, default_source: str = "ALL") -> None:
        """Ensure field operands refer to the governed source catalog."""
        if "field" in condition:
            if str(condition.get("field") or "") not in set(self.available_fields(default_source)):
                raise ValueError("The rule field is not enabled in the governed field catalog.")
            return
        for key in ("all", "any"):
            children = condition.get(key)
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        self._validate_condition_fields(child, default_source)
        nested = condition.get("not")
        if isinstance(nested, dict):
            self._validate_condition_fields(nested, default_source)
        left = condition.get("left")
        right = condition.get("right")
        for operand in (left, right):
            if not isinstance(operand, dict):
                continue
            if operand.get("kind") == "field":
                source = str(operand.get("source") or default_source).strip().upper() or "ALL"
                if source not in {"ALL", *self._configured_source_keys()}:
                    raise ValueError("The rule field source is not governed.")
                if str(operand.get("field") or "") not in set(self.available_fields(source)):
                    raise ValueError("The rule field is not enabled in the governed field catalog.")
            elif operand.get("kind") == "derived":
                for argument in operand.get("arguments", []):
                    if isinstance(argument, dict) and argument.get("kind") == "field":
                        self._validate_condition_fields({"left": argument, "right": {"kind": "literal", "value": None}}, default_source)

    @staticmethod
    def _current_context_version_id(session) -> str | None:
        """Pin newly created rules to the context active at creation time."""
        context = session.scalar(select(RuleContextModel).where(RuleContextModel.context_key == "DEFAULT"))
        if context is None:
            return None
        context_version = session.scalar(select(RuleContextVersionModel).where(
            RuleContextVersionModel.context_id == context.context_id,
            RuleContextVersionModel.version == context.current_version,
        ))
        return context_version.context_version_id if context_version is not None else None

    def set_status(self, rule_id: str, status: str) -> None:
        status = status.upper()
        if status not in {"ACTIVE", "DISABLED"}:
            raise ValueError("Invalid rule status.")
        with orm_session(self.database_path) as session:
            self._rules.set_status(session, rule_id, status)

    def delete_rule(self, rule_id: str) -> dict[str, int]:
        """Delete a rule and every detection produced by that rule.

        Findings and quarantine facts are historical projections of a rule,
        not independent business data. Remove those projections first, then
        the rule versions (which reference the rule), and finally the rule.
        """
        rule_id = str(rule_id or "").strip()
        if not rule_id:
            raise ValueError("Rule not found.")
        with orm_session(self.database_path) as session:
            return self._rules.delete(session, rule_id)

    def evaluate_all_batches(self) -> int:
        """Run active AFTER rules against all historical imported batches."""
        return self._execution.evaluate_all_batches()

    def test_rule(self, rule_id: str, batch_id: str | None = None) -> dict:
        """Preview a rule against local evidence without creating findings.

        This is intentionally available for DRAFT rules so an administrator
        can confirm the rule's scope and matches before activation. The preview
        never changes rule status, source facts, quarantine facts or findings.
        """
        return self._execution.test_rule(rule_id, batch_id)

    def evaluate_batch(self, batch_id: str) -> int:
        """Evaluate active AFTER rules against one persisted import batch."""
        return self._execution.evaluate_batch(batch_id)

    def preflight_batch(self, batch_id: str) -> dict:
        """Evaluate active BEFORE rules against a staged database batch."""
        return self._execution.preflight_batch(batch_id)

    def persist_before_findings(self, batch_id: str, before_results: list[dict] | tuple[dict, ...] = ()) -> int:
        """Persist advisory BEFORE matches after the adapter creates records."""
        return self._execution.persist_before_findings(batch_id, before_results)

    def summary(self) -> dict:
        if not self.database_path.exists():
            return {"open": 0, "critical": 0, "recent": []}
        with orm_session(self.database_path) as session:
            return self._findings.summary(session)

    def list_findings(self, *, status: str = "OPEN", severity: str = "ALL", rule_id: str = "ALL") -> list[RuleFindingModel]:
        with orm_session(self.database_path) as session:
            return self._findings.list_findings(
                session, status=status, severity=severity, rule_id=rule_id
            )

    def count_findings_for_records(self, record_ids: list[str] | tuple[str, ...] | set[str]) -> int:
        """Count rule findings attached to the records in one source import."""
        normalized_ids = {str(record_id).strip() for record_id in record_ids if str(record_id).strip()}
        with orm_session(self.database_path) as session:
            return self._findings.count_for_records(session, normalized_ids)

    def list_quarantine_findings(self, *, status: str = "OPEN", severity: str = "ALL", rule_id: str = "ALL") -> list[dict]:
        """Return findings enriched for the operational quarantine table.

        ``fact_quarantine`` is the master read model. The original
        ``rule_findings`` row remains available as detailed audit evidence.
        """
        with orm_session(self.database_path) as session:
            return self._quarantine.list_findings(
                session,
                status=status,
                severity=severity,
                rule_id=rule_id,
            )

    def update_finding(self, finding_id: str, *, status: str, actor: str, note: str = "") -> RuleFindingModel:
        status = status.upper()
        if status not in {"ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"}:
            raise ValueError("Invalid finding status.")
        if status in {"RESOLVED", "SUPPRESSED"} and not note.strip():
            raise ValueError("A note is required to resolve or suppress a finding.")
        with orm_session(self.database_path) as session:
            now = datetime.now(timezone.utc).isoformat()
            return self._findings.update(
                session,
                finding_id,
                status=status,
                actor=actor,
                note=note.strip(),
                now=now,
            )

    def _create_finding(self, session, rule, version, record, payload, condition, fingerprint: str, now: str) -> bool:
        return self._findings.create(
            session,
            rule=rule,
            version=version,
            record=record,
            payload=payload,
            condition=condition,
            field_key=self._condition_field(condition),
            fingerprint=fingerprint,
            now=now,
        )

    @staticmethod
    def _condition_field(condition: dict) -> str:
        """Expose the first governed field for the quarantine projection."""
        if condition.get("field"):
            return str(condition["field"])
        left = condition.get("left")
        if isinstance(left, dict) and left.get("kind") == "field" and left.get("field"):
            return str(left["field"])
        for key in ("all", "any"):
            children = condition.get(key)
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        field = BusinessRuleService._condition_field(child)
                        if field:
                            return field
        nested = condition.get("not")
        return BusinessRuleService._condition_field(nested) if isinstance(nested, dict) else ""

    @staticmethod
    def _json(value: str) -> dict:
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _matches(self, condition: dict, payload: dict, context_version_id: str | None = None) -> bool:
        """Evaluate with the active local calendar and retain old rule behavior."""
        return ConditionEvaluator(
            configured_rule_calendar(self.database_path, context_version_id=context_version_id)
        ).matches(condition, payload)
