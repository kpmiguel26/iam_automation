"""Read-model queries for operational quarantine findings."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ....infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    DimEmployeeModel,
    FactQuarantineModel,
    IngestionRecordModel,
    RuleFindingModel,
    WorkerModel,
)


class QuarantineRepository:
    """Load the enriched quarantine projection for operational consumers."""

    @classmethod
    def list_findings(
        cls,
        session: Any,
        *,
        status: str,
        severity: str,
        rule_id: str,
    ) -> list[dict]:
        query = select(FactQuarantineModel).order_by(
            FactQuarantineModel.created_at_utc.desc()
        )
        if status != "ALL":
            query = query.where(FactQuarantineModel.status == status)
        if severity != "ALL":
            query = query.where(FactQuarantineModel.severity == severity)
        if rule_id != "ALL":
            query = query.where(FactQuarantineModel.rule_id == rule_id)

        items = []
        for fact in session.scalars(query).all():
            finding = session.get(RuleFindingModel, fact.finding_id)
            if finding is None:
                continue
            rule = session.get(BusinessRuleModel, finding.rule_id)
            version = session.get(BusinessRuleVersionModel, finding.rule_version_id)
            record = session.get(IngestionRecordModel, fact.record_id) if fact.record_id else None
            worker_id = fact.worker_id or fact.employee_key or finding.worker_id
            worker = session.get(WorkerModel, worker_id) if worker_id else None
            employee = session.get(DimEmployeeModel, fact.employee_key) if fact.employee_key else None
            evidence = cls._json(finding.evidence_json)
            condition = cls._json(version.condition_json) if version is not None else {}
            payload = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else {}
            field = str(fact.field_key or condition.get("field") or "")
            actual_value = fact.observed_value or (payload.get(field, "") if field else "")
            worker_name = " ".join(
                part for part in (
                    str(worker.first_name or "") if worker else "",
                    str(worker.last_name or "") if worker else "",
                ) if part
            ).strip()
            if worker is not None:
                worker_name = str(worker.display_name or worker_name or worker.worker_id)
            elif employee is not None:
                worker_name = str(employee.display_name or employee.employee_key)

            items.append({
                "finding": finding,
                "rule_name": str(fact.rule_name or (rule.name if rule is not None else finding.title)),
                "rule_description": str(fact.reason or (rule.description if rule is not None else finding.message)),
                "field": field or "Not specified",
                "operator": str(fact.operator or condition.get("operator") or ""),
                "expected_value": fact.expected_value or condition.get("value", ""),
                "actual_value": actual_value,
                "employee": {
                    "worker_id": str(worker_id or ""),
                    "name": worker_name or "Unmatched employee",
                    "email": str(worker.canonical_email or "") if worker is not None else "",
                    "status": str(worker.status or "") if worker is not None else "",
                },
                "source_system": str(fact.source_system or finding.source_system or (record.source_system if record is not None else "")),
                "source_record_key": str(fact.source_record_key or (record.source_record_key if record is not None else "")),
            })
        return items

    @staticmethod
    def _json(raw: str | None) -> dict:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
