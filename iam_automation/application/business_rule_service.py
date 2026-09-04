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

    def evaluate_batch(self, batch_id: str) -> int:
        """Evaluate active rules against one already-persisted import batch."""
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            rules = session.scalars(
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
