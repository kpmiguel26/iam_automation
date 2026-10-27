"""Advisory bridge from configured business rules to runtime-v2 evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..rules.service import BusinessRuleService
from ...infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    DimSourceModel,
    orm_session,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_configured_rules(
    database_path: Path,
    *,
    phase: str,
    source_id: str,
    source_system_key: str = "",
    rows: tuple[Any, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Evaluate active current-version record rules against parsed v2 rows.

    Evaluation failures are returned as diagnostics. They never reject a row or
    stop ingestion. The legacy rule definitions remain the configuration source;
    findings are written separately with v2 batch/evidence lineage.
    """
    phase = str(phase or "").upper()
    if phase not in {"BEFORE", "AFTER"}:
        raise ValueError("Rule phase must be BEFORE or AFTER.")
    service = BusinessRuleService(database_path)
    findings: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    with orm_session(database_path) as session:
        configured = session.execute(
            select(BusinessRuleModel, BusinessRuleVersionModel)
            .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
            .where(BusinessRuleModel.status == "ACTIVE")
            .where(BusinessRuleVersionModel.status == "ACTIVE")
            .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
            .where(BusinessRuleVersionModel.phase == phase)
        ).all()
        for rule, version in configured:
            try:
                if str(rule.rule_type or "RECORD_CONDITION").upper() != "RECORD_CONDITION":
                    diagnostics.append(f"{rule.name} ({phase}): rule type is not supported by the v2 row evaluator.")
                    continue
                scope = service._json(version.scope_json)
                scoped_source_id = str(scope.get("source_id") or "").strip()
                source_system = str(scope.get("source_system") or "").strip().upper()
                if scoped_source_id:
                    legacy_source = session.get(DimSourceModel, scoped_source_id)
                    if legacy_source is not None and legacy_source.active:
                        source_system = str(legacy_source.source_system or "").upper()
                elif source_system:
                    scoped_source_id = str(session.scalar(
                        select(DimSourceModel.source_id).where(
                            DimSourceModel.source_system == source_system,
                            DimSourceModel.active.is_(True),
                        )
                    ) or "")
                mapped_source_key = str(source_system_key or source_id).strip().upper()
                source_scope_matches = (
                    scoped_source_id == source_id
                    or (bool(source_system) and source_system == mapped_source_key)
                )
                if (scoped_source_id or source_system) and not source_scope_matches:
                    continue
                condition = service._runtime_condition(service._json(version.condition_json), session)
                field_key = service._condition_field(condition)
                for row in rows:
                    if row.issues:
                        continue
                    if service._matches(condition, row.normalized_values, version.context_version_id):
                        actual = row.normalized_values.get(field_key) if field_key else None
                        findings.append({
                            "rule_id": str(rule.rule_id),
                            "rule_version_id": str(version.rule_version_id),
                            "rule_name": str(rule.name),
                            "phase": phase,
                            "row_number": int(row.row_number),
                            "sheet_name": str(row.sheet_name or ""),
                            "field_key": field_key,
                            "severity": str(version.severity or "WARNING").upper(),
                            "condition": condition,
                            "actual_value": actual,
                        })
            except Exception as exc:  # advisory rule errors cannot alter import outcome
                diagnostics.append(f"{rule.name} ({phase}): evaluation failed ({type(exc).__name__}).")
    return findings, diagnostics


def persist_v2_findings(connection, *, findings: list[dict[str, Any]], batch_id: str,
                        source_id: str, source_version_id: str, object_type_id: str,
                        now: str | None = None) -> int:
    """Persist advisory matches without touching legacy findings/quarantine."""
    recorded_at = now or _now()
    created = 0
    for finding in findings:
        evidence = connection.execute(
            """SELECT e.evidence_id, e.row_number, oe.object_id
               FROM engine_v2_evidence e
               LEFT JOIN engine_v2_object_evidence oe ON oe.evidence_id = e.evidence_id
               WHERE e.batch_id = ? AND e.sheet_name = ? AND e.row_number = ?""",
            (batch_id, finding["sheet_name"], finding["row_number"]),
        ).fetchone()
        if evidence is None:
            continue
        fingerprint = hashlib.sha256(
            f"{finding['rule_id']}:{finding['rule_version_id']}:{evidence['evidence_id']}:{finding['phase']}".encode()
        ).hexdigest()
        cursor = connection.execute(
            """INSERT OR IGNORE INTO engine_v2_rule_findings
               (finding_id, rule_id, rule_version_id, rule_name, phase, batch_id,
                evidence_id, object_type_id, object_id, source_id, source_version_id,
                row_number, field_key, severity, status, title, message, evidence_json,
                fingerprint, created_at_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), finding["rule_id"], finding["rule_version_id"],
             finding["rule_name"], finding["phase"], batch_id, str(evidence["evidence_id"]),
             object_type_id or None, evidence["object_id"], source_id, source_version_id,
             int(finding["row_number"]), finding["field_key"], finding["severity"],
             finding["rule_name"], f"Configured advisory rule matched{': ' + finding['field_key'] if finding['field_key'] else '.'}",
             json.dumps({"condition": finding["condition"], "actual_value": finding["actual_value"]},
                        ensure_ascii=False, sort_keys=True, default=str), fingerprint, recorded_at),
        )
        created += int(cursor.rowcount > 0)
    return created
