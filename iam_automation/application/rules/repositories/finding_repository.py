"""SQLite persistence boundary for advisory rule findings."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select

from ....infrastructure.sqlite.orm import (
    DimEmployeeModel,
    DimFieldModel,
    DimSourceModel,
    FactQuarantineModel,
    RuleFindingModel,
)


class FindingRepository:
    """Persist findings and their quarantine read-model projection."""

    @staticmethod
    def summary(session: Any) -> dict:
        open_findings = session.scalars(
            select(FactQuarantineModel)
            .where(FactQuarantineModel.status == "OPEN")
            .order_by(FactQuarantineModel.created_at_utc.desc())
            .limit(8)
        ).all()
        open_count = session.query(FactQuarantineModel).filter(
            FactQuarantineModel.status == "OPEN"
        ).count()
        critical_count = session.query(FactQuarantineModel).filter(
            FactQuarantineModel.status == "OPEN",
            FactQuarantineModel.severity == "CRITICAL",
        ).count()
        return {
            "open": int(open_count),
            "critical": int(critical_count),
            "recent": [{
                "title": item.rule_name,
                "message": item.reason,
                "severity": item.severity,
                "status": item.status,
            } for item in open_findings],
        }

    @staticmethod
    def list_findings(session: Any, *, status: str, severity: str, rule_id: str) -> list[RuleFindingModel]:
        query = select(RuleFindingModel).order_by(RuleFindingModel.created_at_utc.desc())
        if status != "ALL":
            query = query.where(RuleFindingModel.status == status)
        if severity != "ALL":
            query = query.where(RuleFindingModel.severity == severity)
        if rule_id != "ALL":
            query = query.where(RuleFindingModel.rule_id == rule_id)
        return list(session.scalars(query).all())

    @staticmethod
    def count_for_records(session: Any, record_ids: set[str]) -> int:
        if not record_ids:
            return 0
        return int(session.query(FactQuarantineModel).filter(
            FactQuarantineModel.record_id.in_(record_ids)
        ).count())

    @staticmethod
    def create(
        session: Any,
        *,
        rule: Any,
        version: Any,
        record: Any,
        payload: dict,
        condition: dict,
        field_key: str,
        fingerprint: str,
        now: str,
    ) -> bool:
        if session.scalar(select(RuleFindingModel.finding_id).where(
            RuleFindingModel.fingerprint == fingerprint
        )):
            return False

        finding_id = str(uuid.uuid4())
        evidence_json = json.dumps({
            "record_id": record.record_id,
            "source_system": record.source_system,
            "payload": payload,
        }, sort_keys=True)
        session.add(RuleFindingModel(
            finding_id=finding_id,
            rule_id=rule.rule_id,
            rule_version_id=version.rule_version_id,
            batch_id=record.batch_id,
            record_id=record.record_id,
            worker_id=record.matched_worker_id,
            source_system=record.source_system,
            severity=version.severity,
            status="OPEN",
            title=rule.name,
            message=rule.description or "Business rule matched during ingestion.",
            evidence_json=evidence_json,
            fingerprint=fingerprint,
            created_at_utc=now,
            updated_at_utc=now,
        ))
        FindingRepository._create_quarantine_projection(
            session,
            finding_id=finding_id,
            rule=rule,
            version=version,
            record=record,
            payload=payload,
            condition=condition,
            field_key=field_key,
            evidence_json=evidence_json,
            now=now,
        )
        return True

    @staticmethod
    def _create_quarantine_projection(
        session: Any,
        *,
        finding_id: str,
        rule: Any,
        version: Any,
        record: Any,
        payload: dict,
        condition: dict,
        field_key: str,
        evidence_json: str,
        now: str,
    ) -> None:
        source = session.scalar(select(DimSourceModel).where(
            DimSourceModel.source_system == record.source_system
        ))
        field = session.scalar(select(DimFieldModel).where(
            DimFieldModel.field_key == field_key
        )) if field_key else None
        expected = condition.get("value", "")
        if "right" in condition and isinstance(condition.get("right"), dict):
            expected = condition["right"].get("value", "")
        expected_text = json.dumps(expected, sort_keys=True) if isinstance(expected, (list, dict)) else str(expected or "")
        actual = payload.get(field_key, "") if field_key else ""
        actual_text = json.dumps(actual, sort_keys=True) if isinstance(actual, (list, dict)) else str(actual or "")
        employee_key = record.matched_worker_id if (
            record.matched_worker_id
            and session.get(DimEmployeeModel, record.matched_worker_id) is not None
        ) else None
        session.add(FactQuarantineModel(
            quarantine_fact_id=f"quarantine:{finding_id}",
            finding_id=finding_id,
            employee_key=employee_key,
            worker_id=record.matched_worker_id,
            batch_id=record.batch_id,
            record_id=record.record_id,
            source_id=source.source_id if source is not None else None,
            field_id=field.field_id if field is not None else None,
            source_system=record.source_system,
            source_record_key=record.source_record_key,
            rule_id=rule.rule_id,
            rule_version_id=version.rule_version_id,
            field_key=field_key,
            operator=str(condition.get("operator") or ""),
            expected_value=expected_text,
            observed_value=actual_text,
            severity=version.severity,
            status="OPEN",
            rule_name=rule.name,
            reason=rule.description or "Business rule matched during ingestion.",
            evidence_json=evidence_json,
            created_at_utc=now,
            updated_at_utc=now,
        ))

    @staticmethod
    def update(
        session: Any,
        finding_id: str,
        *,
        status: str,
        actor: str,
        note: str,
        now: str,
    ) -> RuleFindingModel:
        finding = session.get(RuleFindingModel, finding_id)
        if finding is None:
            raise ValueError("Finding not found.")
        finding.status = status
        finding.updated_at_utc = now
        finding.acknowledged_by = actor
        finding.acknowledged_at_utc = now
        try:
            evidence = json.loads(finding.evidence_json or "{}")
        except (TypeError, ValueError):
            evidence = {}
        if not isinstance(evidence, dict):
            evidence = {}
        evidence["last_action_note"] = note
        finding.evidence_json = json.dumps(evidence, sort_keys=True)
        facts = session.scalars(select(FactQuarantineModel).where(
            FactQuarantineModel.finding_id == finding_id
        )).all()
        for fact in facts:
            fact.status = status
            fact.updated_at_utc = now
            fact.resolved_by = actor
            fact.resolved_at_utc = now if status in {"RESOLVED", "SUPPRESSED"} else None
        return finding
