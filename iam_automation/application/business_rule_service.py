"""Evaluate allow-listed business rules after records are persisted in SQLite."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    IngestionRecordModel,
    RuleFindingModel,
    orm_session,
)


class BusinessRuleService:
    """Phase-one rule engine: findings only, never an import gate."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    ALLOWED_OPERATORS = ("exists", "missing", "equals", "not_equals", "in")
    ALLOWED_SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")

    def list_rules(self) -> list[dict]:
        with orm_session(self.database_path) as session:
            rules = session.scalars(select(BusinessRuleModel).order_by(BusinessRuleModel.name.asc())).all()
            result = []
            for rule in rules:
                version = session.scalar(select(BusinessRuleVersionModel).where(BusinessRuleVersionModel.rule_id == rule.rule_id, BusinessRuleVersionModel.version == rule.current_version))
                result.append({"rule": rule, "version": version})
            return result

    def create_rule(self, *, name: str, description: str, field: str, operator: str, value: str, severity: str, actor: str) -> str:
        name, field, operator, severity = name.strip(), field.strip(), operator.strip(), severity.strip().upper()
        if not name or not field or operator not in self.ALLOWED_OPERATORS or severity not in self.ALLOWED_SEVERITIES:
            raise ValueError("Name, field, valid operator and severity are required.")
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        condition = {"field": field, "operator": operator}
        if operator in {"equals", "not_equals"}: condition["value"] = value
        if operator == "in": condition["value"] = [item.strip() for item in value.split(",") if item.strip()]
        with orm_session(self.database_path) as session:
            session.add(BusinessRuleModel(rule_id=rule_id, name=name, description=description.strip(), status="DRAFT", current_version=1, created_by=actor, created_at_utc=now, updated_at_utc=now))
            session.add(BusinessRuleVersionModel(rule_version_id=f"{rule_id}:1", rule_id=rule_id, version=1, condition_json=json.dumps(condition, sort_keys=True), scope_json="{}", severity=severity, status="DRAFT", created_by=actor, created_at_utc=now))
        return rule_id

    def set_status(self, rule_id: str, status: str) -> None:
        status = status.upper()
        if status not in {"ACTIVE", "DISABLED"}:
            raise ValueError("Invalid rule status.")
        with orm_session(self.database_path) as session:
            rule = session.get(BusinessRuleModel, rule_id)
            if rule is None: raise ValueError("Rule not found.")
            rule.status = status
            version = session.scalar(select(BusinessRuleVersionModel).where(BusinessRuleVersionModel.rule_id == rule_id, BusinessRuleVersionModel.version == rule.current_version))
            if version is not None: version.status = status

    def evaluate_all_batches(self) -> int:
        """Run active rules against all historical imported batches."""
        if not self.database_path.exists():
            return 0
        with orm_session(self.database_path) as session:
            batch_ids = session.scalars(select(IngestionRecordModel.batch_id).distinct()).all()
        return sum(self.evaluate_batch(str(batch_id)) for batch_id in batch_ids)

    def evaluate_batch(self, batch_id: str) -> int:
        """Evaluate active rules against one already-persisted import batch."""
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            # A multi-entity SELECT must use execute(); scalars() intentionally
            # returns only the first selected entity (BusinessRuleModel).
            rules = session.execute(
                select(BusinessRuleModel, BusinessRuleVersionModel)
                .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
            ).all()
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
            for rule, version in rules:
                scope = self._json(version.scope_json)
                for record in records:
                    if scope.get("source_system") and scope["source_system"] != record.source_system:
                        continue
                    payload = self._json(record.normalized_json or record.payload_json)
                    if not self._matches(self._json(version.condition_json), payload):
                        continue
                    fingerprint = hashlib.sha256(f"{rule.rule_id}:{version.rule_version_id}:{record.record_id}".encode()).hexdigest()
                    if session.scalar(select(RuleFindingModel.finding_id).where(RuleFindingModel.fingerprint == fingerprint)):
                        continue
                    session.add(RuleFindingModel(
                        finding_id=str(uuid.uuid4()), rule_id=rule.rule_id, rule_version_id=version.rule_version_id,
                        batch_id=batch_id, record_id=record.record_id, worker_id=record.matched_worker_id,
                        source_system=record.source_system, severity=version.severity, status="OPEN",
                        title=rule.name, message=rule.description or "Business rule matched after import.",
                        evidence_json=json.dumps({"record_id": record.record_id, "source_system": record.source_system, "payload": payload}, sort_keys=True),
                        fingerprint=fingerprint, created_at_utc=now, updated_at_utc=now,
                    ))
                    created += 1
        return created

    def summary(self) -> dict:
        if not self.database_path.exists():
            return {"open": 0, "critical": 0, "recent": []}
        with orm_session(self.database_path) as session:
            open_findings = session.scalars(select(RuleFindingModel).where(RuleFindingModel.status == "OPEN").order_by(RuleFindingModel.created_at_utc.desc()).limit(8)).all()
            return {
                "open": int(session.scalar(select(func.count(RuleFindingModel.finding_id)).where(RuleFindingModel.status == "OPEN")) or 0),
                "critical": int(session.scalar(select(func.count(RuleFindingModel.finding_id)).where(RuleFindingModel.status == "OPEN", RuleFindingModel.severity == "CRITICAL")) or 0),
                "recent": [{"title": item.title, "message": item.message, "severity": item.severity, "status": item.status} for item in open_findings],
            }

    def list_findings(self, *, status: str = "OPEN", severity: str = "ALL", rule_id: str = "ALL") -> list[RuleFindingModel]:
        with orm_session(self.database_path) as session:
            query = select(RuleFindingModel).order_by(RuleFindingModel.created_at_utc.desc())
            if status != "ALL": query = query.where(RuleFindingModel.status == status)
            if severity != "ALL": query = query.where(RuleFindingModel.severity == severity)
            if rule_id != "ALL": query = query.where(RuleFindingModel.rule_id == rule_id)
            return list(session.scalars(query).all())

    def update_finding(self, finding_id: str, *, status: str, actor: str, note: str = "") -> RuleFindingModel:
        status = status.upper()
        if status not in {"ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"}:
            raise ValueError("Invalid finding status.")
        if status in {"RESOLVED", "SUPPRESSED"} and not note.strip():
            raise ValueError("A note is required to resolve or suppress a finding.")
        with orm_session(self.database_path) as session:
            finding = session.get(RuleFindingModel, finding_id)
            if finding is None: raise ValueError("Finding not found.")
            now = datetime.now(timezone.utc).isoformat()
            finding.status = status
            finding.updated_at_utc = now
            finding.acknowledged_by = actor
            finding.acknowledged_at_utc = now
            evidence = self._json(finding.evidence_json)
            evidence["last_action_note"] = note.strip()
            finding.evidence_json = json.dumps(evidence, sort_keys=True)
            return finding

    @staticmethod
    def _json(value: str) -> dict:
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @classmethod
    def _matches(cls, condition: dict, payload: dict) -> bool:
        if "all" in condition:
            return all(cls._matches(item, payload) for item in condition["all"])
        if "any" in condition:
            return any(cls._matches(item, payload) for item in condition["any"])
        field = condition.get("field")
        operator = condition.get("operator")
        actual = payload.get(field) if field else None
        expected = condition.get("value")
        if operator == "exists": return field in payload
        if operator == "missing": return field not in payload or actual in (None, "")
        if operator == "equals": return actual == expected
        if operator == "not_equals": return actual != expected
        if operator == "in": return actual in (expected or [])
        return False
