"""Application orchestration for evaluating configured business rules.

The compatibility service still owns persistence helpers and public legacy
methods. This module owns the lifecycle orchestration for previews, BEFORE
preflight evaluation, AFTER batch evaluation and advisory finding creation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ...infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    DimSourceModel,
    ImportBatchModel,
    IngestionRecordModel,
    RuleFindingModel,
    orm_session,
)
from .base import RuleResult
from .evidence import EvidenceRepository, SqliteEvidenceRepository


class RuleExecutionService:
    """Coordinate advisory rule execution without making imports blockable."""

    def __init__(self, service: Any, evidence_repository: EvidenceRepository | None = None):
        self.service = service
        self.evidence_repository = evidence_repository or SqliteEvidenceRepository()

    @property
    def database_path(self) -> Path:
        return self.service.database_path

    def evaluate_all_batches(self) -> int:
        """Run active AFTER rules against all historical imported batches."""
        if not self.database_path.exists():
            return 0
        with orm_session(self.database_path) as session:
            batch_ids = session.scalars(select(IngestionRecordModel.batch_id).distinct()).all()
        return sum(self.evaluate_batch(str(batch_id)) for batch_id in batch_ids)

    def test_rule(self, rule_id: str, batch_id: str | None = None) -> dict:
        """Preview a rule against local evidence without creating findings."""
        rule_id = str(rule_id or "").strip()
        selected_batch = str(batch_id or "").strip()
        if not rule_id:
            raise ValueError("Rule not found.")
        with orm_session(self.database_path) as session:
            rule = session.get(BusinessRuleModel, rule_id)
            if rule is None:
                raise ValueError("Rule not found.")
            version = session.scalar(select(BusinessRuleVersionModel).where(
                BusinessRuleVersionModel.rule_id == rule_id,
                BusinessRuleVersionModel.version == rule.current_version,
            ))
            if version is None:
                raise ValueError("Rule version not found.")
            scope = self.service._json(version.scope_json)
            condition = self.service._runtime_condition(self.service._json(version.condition_json), session)
            matches: list[dict] = []
            evaluated = 0
            batch_ids = [selected_batch] if selected_batch else list(session.scalars(select(IngestionRecordModel.batch_id).distinct()).all())
            scoped_source_id = self._scope_source_id(session, scope)
            for candidate_batch_id in batch_ids:
                batch = self.evidence_repository.batch_for_id(session, str(candidate_batch_id))
                if batch is None or (scoped_source_id is not None and batch.source_id != scoped_source_id):
                    continue
                records = {
                    str(record.record_id): record
                    for record in session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == str(candidate_batch_id))).all()
                }
                for normalized in batch.records:
                    evaluated += 1
                    payload = normalized.fields
                    if not self.service._matches(condition, payload, version.context_version_id):
                        continue
                    record = records.get(normalized.record_id)
                    field_key = self.service._condition_field(condition)
                    actual = payload.get(field_key, "") if field_key else ""
                    matches.append({
                        "batch_id": batch.batch_id,
                        "record_id": normalized.record_id,
                        "source_id": normalized.source_id,
                        "source_system": record.source_system if record is not None else "",
                        "source_record_key": normalized.metadata.source_record_key,
                        "row_number": normalized.metadata.row_number,
                        "field": field_key,
                        "actual_value": actual,
                    })
            return {
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "rule_status": rule.status,
                "phase": version.phase,
                "batch_id": selected_batch or "ALL",
                "evaluated": evaluated,
                "match_count": len(matches),
                "matches": matches,
            }

    def evaluate_batch(self, batch_id: str) -> int:
        """Evaluate active AFTER rules against one persisted import batch."""
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            batch = self.evidence_repository.batch_for_id(session, batch_id)
            if batch is None:
                return 0
            rules = session.execute(
                select(BusinessRuleModel, BusinessRuleVersionModel)
                .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
                .where(BusinessRuleVersionModel.phase == "AFTER")
            ).all()
            records = {
                str(record.record_id): record
                for record in session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
            }
            payloads = {}
            for rule, version in rules:
                scope = self.service._json(version.scope_json)
                scoped_source_id = self._scope_source_id(session, scope)
                if scoped_source_id is not None and scoped_source_id != batch.source_id:
                    continue
                condition = self.service._runtime_condition(self.service._json(version.condition_json), session)
                for normalized in batch.records:
                    record = records.get(normalized.record_id)
                    if record is None:
                        continue
                    payload_key = (normalized.record_id, version.rule_version_id)
                    if payload_key not in payloads:
                        payloads[payload_key] = normalized.fields
                    payload = payloads[payload_key]
                    if not self.service._matches(condition, payload, version.context_version_id):
                        continue
                    fingerprint = hashlib.sha256(
                        f"{rule.rule_id}:{version.rule_version_id}:{record.record_id}".encode()
                    ).hexdigest()
                    if session.scalar(select(RuleFindingModel.finding_id).where(RuleFindingModel.fingerprint == fingerprint)):
                        continue
                    if self.service._create_finding(session, rule, version, record, payload, condition, fingerprint, now):
                        created += 1
        return created

    @staticmethod
    def _scope_source_id(session: Any, scope: dict) -> str | None:
        """Resolve stable source scopes, with a compatibility fallback for old rules."""
        if scope.get("source_id"):
            return str(scope["source_id"])
        source_system = str(scope.get("source_system") or "").strip().upper()
        if not source_system:
            return None
        source_id = session.scalar(
            select(DimSourceModel.source_id).where(
                DimSourceModel.source_system == source_system,
                DimSourceModel.active.is_(True),
            )
        )
        return str(source_id) if source_id is not None else None

    def preflight_batch(self, batch_id: str) -> dict:
        """Evaluate active BEFORE rules against the shared staged contract."""
        batch_id = str(batch_id or "").strip()
        if not batch_id:
            return {"batch_id": "", "evaluated_rows": 0, "matches": []}
        if not self.database_path.exists():
            return {"batch_id": batch_id, "evaluated_rows": 0, "matches": []}
        with orm_session(self.database_path) as session:
            has_before_rules = session.scalar(
                select(BusinessRuleVersionModel.rule_version_id)
                .join(BusinessRuleModel, BusinessRuleModel.rule_id == BusinessRuleVersionModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
                .where(BusinessRuleVersionModel.phase == "BEFORE")
                .limit(1)
            )
        if has_before_rules is None:
            return {"batch_id": batch_id, "evaluated_rows": 0, "matches": []}
        matches: list[dict] = []
        with orm_session(self.database_path) as session:
            batch = self.evidence_repository.batch_for_id(session, batch_id)
            if batch is None:
                return {"batch_id": batch_id, "evaluated_rows": 0, "matches": []}
            rules = session.execute(
                select(BusinessRuleModel, BusinessRuleVersionModel)
                .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
                .where(BusinessRuleVersionModel.phase == "BEFORE")
            ).all()
            for rule, version in rules:
                scope = self.service._json(version.scope_json)
                condition = self.service._runtime_condition(self.service._json(version.condition_json), session)
                scoped_source_id = self._scope_source_id(session, scope)
                if scoped_source_id is not None and scoped_source_id != batch.source_id:
                    continue
                for evidence in batch.records:
                    if not isinstance(evidence.fields, dict):
                        continue
                    payload = evidence.fields
                    if self.service._matches(condition, payload, version.context_version_id):
                        matches.append({
                            "rule_id": rule.rule_id,
                            "rule_version_id": version.rule_version_id,
                            "source_id": evidence.source_id,
                            "source_record_key": evidence.metadata.source_record_key,
                            "row_number": evidence.metadata.row_number,
                            "record_id": evidence.record_id,
                        })
        return {"batch_id": batch_id, "evaluated_rows": len(batch.records), "matches": matches}

    def persist_before_findings(self, batch_id: str, before_results: tuple[RuleResult, ...] = ()) -> int:
        """Persist advisory BEFORE matches after the adapter creates records."""
        matches = [
            match
            for result in before_results or ()
            for match in (result.details or {}).get("matches", [])
            if isinstance(match, dict)
        ]
        if not matches:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            if session.get(ImportBatchModel, batch_id) is None:
                return 0
            records = {
                str(record.record_id): record
                for record in session.scalars(
                    select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)
                ).all()
            }
            for match in matches:
                record = records.get(str(match.get("record_id") or ""))
                if record is None:
                    continue
                rule = session.get(BusinessRuleModel, str(match.get("rule_id") or ""))
                version = session.get(BusinessRuleVersionModel, str(match.get("rule_version_id") or ""))
                if rule is None or version is None:
                    continue
                payload = self.evidence_repository.fields_for_record(session, record)
                condition = self.service._runtime_condition(self.service._json(version.condition_json), session)
                fingerprint = hashlib.sha256(
                    f"{rule.rule_id}:{version.rule_version_id}:{record.record_id}".encode()
                ).hexdigest()
                if self.service._create_finding(session, rule, version, record, payload, condition, fingerprint, now):
                    created += 1
        return created
