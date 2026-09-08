"""Evaluate advisory business rules against persisted source evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

from ..infrastructure.sqlite.star_schema_writer import StarSchemaWriter
from ..infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    DimEmployeeModel,
    DimFieldModel,
    DimSourceModel,
    FactQuarantineModel,
    FactSourceSnapshotModel,
    FactWorkerFieldModel,
    ImportBatchModel,
    IngestionRecordModel,
    RuleFindingModel,
    SourceFieldMappingModel,
    WorkerModel,
    orm_session,
)
from ..source_adapters.accessnow import merge_rows as merge_accessnow_rows
from ..source_adapters.accessnow import normalize_row as normalize_accessnow_row
from ..source_adapters.accessnow import read_rows as read_accessnow_rows
from ..source_adapters.master_roster import normalize_row as normalize_master_roster_row
from ..source_adapters.master_roster import read_rows as read_master_roster_rows
from ..source_adapters.roster_lock import normalize_row as normalize_roster_lock_row
from ..source_adapters.roster_lock import read_rows as read_roster_lock_rows
from ..source_adapters.rsr_supplier.reader import read_rows as read_rsr_rows


class BusinessRuleService:
    """Phase-one rule engine: findings only, never an import gate."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    ALLOWED_OPERATORS = ("exists", "missing", "equals", "not_equals", "contains", "in")
    ALLOWED_SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
    ALLOWED_PHASES = ("BEFORE", "AFTER")
    SOURCE_FIELDS = {
        "ROSTER_LOCK": (
            "vendor_employee_id", "vendor_name", "first_name", "last_name", "email",
            "job_title", "supervisor_name", "onboarding_date", "production_start_date",
            "assignment_status", "work_order_id",
        ),
        "MASTER_ROSTER": (
            "employee_number", "employee_name", "first_name", "last_name", "email",
            "nuid_login_id", "npn_login_id", "parent_client", "client", "program", "project",
            "site_hr_location", "supervisor_employee_number", "supervisor_name", "job_code",
            "job_title", "hire_date", "project_start_date", "production_start_date",
            "actual_termination_date", "term_reason", "assignment_status", "user_principal_name",
        ),
        "RSR_SUPPLIER_WORKER_DETAILS": (
            "supplier_reference", "worker_id", "buyer_reference", "work_order_id", "worker",
            "first_name", "last_name", "email", "vendor_name", "worker_status", "worker_start_date",
            "worker_end_date", "job_title", "supervisor_name", "statement_of_work", "supplier_name",
        ),
        "ACCESSNOW": (
            "accessnow_employee_id", "accessnow_nuid", "first_name", "last_name", "email",
            "vendor_name", "job_title", "manager_nuid", "supervisor_name", "sponsor_nuid",
            "sponsor_name", "accessnow_status", "termination_date", "onboarding_date",
            "production_start_date",
        ),
    }
    SOURCE_LABELS = {
        "ROSTER_LOCK": "Roster Lock",
        "MASTER_ROSTER": "Master Roster",
        "RSR_SUPPLIER_WORKER_DETAILS": "Fieldglass / RSR Supplier Worker Details",
        "ACCESSNOW": "AccessNow",
    }
    DEFAULT_FIELDS = (
        "email",
        "status",
        "accessnow_status",
        "termination_date",
        "onboarding_date",
        "vendor_name",
        "job_title",
    )
    OPERATOR_LABELS = {
        "exists": "is present",
        "missing": "is missing",
        "equals": "equals",
        "not_equals": "does not equal",
        "contains": "contains",
        "in": "is one of",
    }
    SEVERITY_LABELS = {
        "INFO": "Informational",
        "WARNING": "Needs review",
        "ERROR": "Important review",
        "CRITICAL": "Urgent review",
    }
    PHASE_LABELS = {"BEFORE": "Before import", "AFTER": "After import"}
    PHASE_DESCRIPTIONS = {
        "BEFORE": "Checks the incoming report before it is saved.",
        "AFTER": "Checks the saved records after the import completes.",
    }
    STATUS_LABELS = {"ACTIVE": "Enabled", "DRAFT": "Draft", "DISABLED": "Disabled"}

    def list_rules(self) -> list[dict]:
        with orm_session(self.database_path) as session:
            rules = session.scalars(select(BusinessRuleModel).order_by(BusinessRuleModel.name.asc())).all()
            result = []
            for rule in rules:
                version = session.scalar(select(BusinessRuleVersionModel).where(BusinessRuleVersionModel.rule_id == rule.rule_id, BusinessRuleVersionModel.version == rule.current_version))
                scope = self._json(version.scope_json) if version is not None else {}
                condition = self._json(version.condition_json) if version is not None else {}
                source_system = str(scope.get("source_system") or "ALL")
                phase = str(version.phase or "AFTER") if version is not None else "AFTER"
                severity = str(version.severity or "WARNING") if version is not None else "WARNING"
                result.append({"rule": rule, "version": version, "execution_phase": phase, "source_system": source_system, "source_label": "All reports" if source_system == "ALL" else self.SOURCE_LABELS.get(source_system, source_system)})
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

    def available_sources(self) -> tuple[dict[str, str], ...]:
        return ({"key": "ALL", "label": "All reports", "description": "Evaluate the rule against every source."}, *tuple({"key": key, "label": label, "description": f"Only fields from {label}."} for key, label in self.SOURCE_LABELS.items()))

    def available_fields(self, source_system: str = "ALL") -> tuple[str, ...]:
        """Return known source fields for the guided rule builder."""
        with orm_session(self.database_path) as session:
            fields = session.scalars(
                select(DimFieldModel.field_key).where(
                    DimFieldModel.active.is_(True), DimFieldModel.rule_enabled.is_(True)
                ).order_by(DimFieldModel.field_key.asc())
            ).all()
        source_system = str(source_system or "ALL").strip().upper()
        if source_system in self.SOURCE_FIELDS:
            with orm_session(self.database_path) as session:
                source = session.scalar(select(DimSourceModel).where(DimSourceModel.source_system == source_system))
                observed: set[str] = set()
                if source is not None:
                    observed.update(session.scalars(
                        select(SourceFieldMappingModel.source_field_key).where(
                            SourceFieldMappingModel.source_id == source.source_id,
                            SourceFieldMappingModel.active.is_(True),
                        )
                    ).all())
                    # Backfill visibility for databases created before the
                    # source-field catalog started being populated.
                    observed.update(session.scalars(
                        select(DimFieldModel.field_key)
                        .join(FactWorkerFieldModel, FactWorkerFieldModel.field_id == DimFieldModel.field_id)
                        .join(FactSourceSnapshotModel, FactSourceSnapshotModel.snapshot_id == FactWorkerFieldModel.snapshot_id)
                        .where(
                            FactSourceSnapshotModel.source_id == source.source_id,
                            DimFieldModel.active.is_(True),
                            DimFieldModel.rule_enabled.is_(True),
                        )
                    ).all())
                return tuple(sorted({*self.SOURCE_FIELDS[source_system], *(str(field) for field in observed if str(field).strip())}))
        return tuple(sorted({*self.DEFAULT_FIELDS, *(str(field) for field in fields if str(field).strip())}))

    def create_rule(self, *, name: str, description: str, field: str, operator: str, value: str, severity: str, actor: str, phase: str = "AFTER", source_system: str = "ALL") -> str:
        name, field, operator, severity, phase, source_system = name.strip(), field.strip(), operator.strip(), severity.strip().upper(), phase.strip().upper(), source_system.strip().upper() or "ALL"
        if not name or not field or operator not in self.ALLOWED_OPERATORS or severity not in self.ALLOWED_SEVERITIES or phase not in self.ALLOWED_PHASES or source_system not in {"ALL", *self.SOURCE_FIELDS} or field not in set(self.available_fields(source_system)) or (operator in {"equals", "not_equals", "contains", "in"} and not value):
            raise ValueError("Name, phase, field, valid operator and severity are required.")
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        condition = {"field": field, "operator": operator}
        if operator in {"equals", "not_equals", "contains"}: condition["value"] = value
        if operator == "in": condition["value"] = [item.strip() for item in value.split(",") if item.strip()]
        scope = {} if source_system == "ALL" else {"source_system": source_system}
        with orm_session(self.database_path) as session:
            session.add(BusinessRuleModel(rule_id=rule_id, name=name, description=description.strip(), status="DRAFT", current_version=1, created_by=actor, created_at_utc=now, updated_at_utc=now))
            session.add(BusinessRuleVersionModel(rule_version_id=f"{rule_id}:1", rule_id=rule_id, version=1, phase=phase, condition_json=json.dumps(condition, sort_keys=True), scope_json=json.dumps(scope, sort_keys=True), severity=severity, status="DRAFT", created_by=actor, created_at_utc=now))
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

    def evaluate_all_batches(self) -> int:
        """Run active AFTER rules against all historical imported batches."""
        if not self.database_path.exists():
            return 0
        with orm_session(self.database_path) as session:
            batch_ids = session.scalars(select(IngestionRecordModel.batch_id).distinct()).all()
        return sum(self.evaluate_batch(str(batch_id)) for batch_id in batch_ids)

    def evaluate_batch(self, batch_id: str) -> int:
        """Evaluate active AFTER rules against one persisted import batch."""
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            # A destructive testing reset may finish between the adapter and
            # the AFTER callback. Do not recreate quarantine facts for a
            # batch that no longer exists.
            if session.get(ImportBatchModel, batch_id) is None:
                return 0
            # A multi-entity SELECT must use execute(); scalars() intentionally
            # returns only the first selected entity (BusinessRuleModel).
            rules = session.execute(
                select(BusinessRuleModel, BusinessRuleVersionModel)
                .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
                .where(BusinessRuleVersionModel.phase == "AFTER")
            ).all()
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
            payloads = {}
            for rule, version in rules:
                scope = self._json(version.scope_json)
                for record in records:
                    if scope.get("source_system") and scope["source_system"] != record.source_system:
                        continue
                    # Valid imports clear their JSON once source facts exist.
                    # Read those facts once per record, retaining compatibility
                    # with legacy and quarantine rows during the transition.
                    if record.record_id not in payloads:
                        try:
                            payload = StarSchemaWriter.payload_for_record(session, record)
                        except (TypeError, ValueError):
                            payload = {}
                        payloads[record.record_id] = payload if isinstance(payload, dict) else {}
                    payload = payloads[record.record_id]
                    if not self._matches(self._json(version.condition_json), payload):
                        continue
                    fingerprint = hashlib.sha256(f"{rule.rule_id}:{version.rule_version_id}:{record.record_id}".encode()).hexdigest()
                    if session.scalar(select(RuleFindingModel.finding_id).where(RuleFindingModel.fingerprint == fingerprint)):
                        continue
                    condition = self._json(version.condition_json)
                    if self._create_finding(session, rule, version, record, payload, condition, fingerprint, now):
                        created += 1
        return created

    def preflight_file(self, source_system: str, path: Path) -> dict:
        """Evaluate active BEFORE rules against normalized source rows.

        This method intentionally has no database side effects. The
        orchestrator runs it before the adapter; matching rows are carried in
        the advisory result and persisted against the resulting batch only
        after the adapter has created its ingestion records.
        """
        source_system = str(source_system or "").strip().upper()
        if not self.database_path.exists():
            return {"source_system": source_system, "evaluated_rows": 0, "matches": []}
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
            return {"source_system": source_system, "evaluated_rows": 0, "matches": []}
        rows = self._preflight_rows(source_system, path)
        matches: list[dict] = []
        with orm_session(self.database_path) as session:
            rules = session.execute(
                select(BusinessRuleModel, BusinessRuleVersionModel)
                .join(BusinessRuleVersionModel, BusinessRuleVersionModel.rule_id == BusinessRuleModel.rule_id)
                .where(BusinessRuleModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.status == "ACTIVE")
                .where(BusinessRuleVersionModel.version == BusinessRuleModel.current_version)
                .where(BusinessRuleVersionModel.phase == "BEFORE")
            ).all()
            for rule, version in rules:
                scope = self._json(version.scope_json)
                if scope.get("source_system") and scope["source_system"] != source_system:
                    continue
                condition = self._json(version.condition_json)
                for row_number, source_record_key, payload in rows:
                    if self._matches(condition, payload):
                        matches.append({
                            "rule_id": rule.rule_id,
                            "rule_version_id": version.rule_version_id,
                            "source_system": source_system,
                            "source_record_key": source_record_key,
                            "row_number": row_number,
                        })
        return {"source_system": source_system, "evaluated_rows": len(rows), "matches": matches}

    def persist_before_findings(self, batch_id: str, before_results: list[dict] | tuple[dict, ...] = ()) -> int:
        """Persist advisory BEFORE matches after the adapter creates records."""
        matches = [
            match
            for result in before_results or ()
            for match in (result.get("details") or {}).get("matches", [])
            if isinstance(match, dict)
        ]
        if not matches:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        created = 0
        with orm_session(self.database_path) as session:
            if session.get(ImportBatchModel, batch_id) is None:
                return 0
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.batch_id == batch_id)).all()
            record_index = {(record.source_system, record.source_record_key, record.row_number): record for record in records}
            fallback_index = {(record.source_system, record.source_record_key): record for record in records}
            for match in matches:
                source_system = str(match.get("source_system") or "").upper()
                if not source_system:
                    continue
                record = record_index.get((
                    source_system,
                    str(match.get("source_record_key") or ""),
                    int(match.get("row_number") or 0),
                )) or fallback_index.get((
                    source_system,
                    str(match.get("source_record_key") or ""),
                ))
                if record is None:
                    continue
                rule = session.get(BusinessRuleModel, str(match.get("rule_id") or ""))
                version = session.get(BusinessRuleVersionModel, str(match.get("rule_version_id") or ""))
                if rule is None or version is None:
                    continue
                payload = StarSchemaWriter.payload_for_record(session, record)
                condition = self._json(version.condition_json)
                fingerprint = hashlib.sha256(f"{rule.rule_id}:{version.rule_version_id}:{record.record_id}".encode()).hexdigest()
                if self._create_finding(session, rule, version, record, payload, condition, fingerprint, now):
                    created += 1
        return created

    @classmethod
    def _preflight_rows(cls, source_system: str, path: Path) -> list[tuple[int, str, dict]]:
        if source_system == "ROSTER_LOCK":
            content = path.read_bytes()
            return [
                (number, f"{normalized.get('vendor_name', '')}:{normalized.get('vendor_employee_id', '')}", normalized)
                for number, raw in enumerate(read_roster_lock_rows(content), start=2)
                for normalized in [cls._json_safe(normalize_roster_lock_row({str(key).strip(): cls._json_value(value) for key, value in raw.items() if key is not None and str(key).strip()}))]
            ]
        if source_system == "MASTER_ROSTER":
            content = path.read_bytes()
            return [
                (number, str(normalized.get("employee_number") or "").strip(), normalized)
                for number, raw in read_master_roster_rows(content)
                for normalized in [cls._json_safe(normalize_master_roster_row({str(key): cls._json_value(value) for key, value in raw.items() if key}))]
            ]
        if source_system == "RSR_SUPPLIER_WORKER_DETAILS":
            return [
                (number, f"{payload.get('supplier_reference') or payload.get('worker_id') or 'ROW'}:{number}", payload)
                for number, payload in read_rsr_rows(path)
            ]
        if source_system == "ACCESSNOW":
            rows = []
            for source_path in sorted(path.iterdir()):
                if not source_path.is_file() or source_path.suffix.lower() not in {".csv", ".xlsx"} or source_path.name.startswith("."):
                    continue
                content = source_path.read_bytes()
                rows.extend((source_path, number, normalize_accessnow_row(raw)) for number, raw in read_accessnow_rows(source_path, content))
            merged, _ = merge_accessnow_rows(rows)
            return [
                (number, str(payload.get("accessnow_employee_id") or f"ROW:{source_path.name}:{original_number}"), payload)
                for number, (source_path, original_number, payload) in enumerate(merged.values(), start=2)
            ]
        return []

    @staticmethod
    def _json_value(value):
        try:
            from datetime import date, datetime
            return value.isoformat() if isinstance(value, (date, datetime)) else value
        except AttributeError:
            return value

    @staticmethod
    def _json_safe(value):
        return json.loads(json.dumps(value, default=str))

    def summary(self) -> dict:
        if not self.database_path.exists():
            return {"open": 0, "critical": 0, "recent": []}
        with orm_session(self.database_path) as session:
            open_findings = session.scalars(select(FactQuarantineModel).where(FactQuarantineModel.status == "OPEN").order_by(FactQuarantineModel.created_at_utc.desc()).limit(8)).all()
            return {
                "open": int(session.scalar(select(func.count(FactQuarantineModel.quarantine_fact_id)).where(FactQuarantineModel.status == "OPEN")) or 0),
                "critical": int(session.scalar(select(func.count(FactQuarantineModel.quarantine_fact_id)).where(FactQuarantineModel.status == "OPEN", FactQuarantineModel.severity == "CRITICAL")) or 0),
                "recent": [{"title": item.rule_name, "message": item.reason, "severity": item.severity, "status": item.status} for item in open_findings],
            }

    def list_findings(self, *, status: str = "OPEN", severity: str = "ALL", rule_id: str = "ALL") -> list[RuleFindingModel]:
        with orm_session(self.database_path) as session:
            query = select(RuleFindingModel).order_by(RuleFindingModel.created_at_utc.desc())
            if status != "ALL": query = query.where(RuleFindingModel.status == status)
            if severity != "ALL": query = query.where(RuleFindingModel.severity == severity)
            if rule_id != "ALL": query = query.where(RuleFindingModel.rule_id == rule_id)
            return list(session.scalars(query).all())

    def count_findings_for_records(self, record_ids: list[str] | tuple[str, ...] | set[str]) -> int:
        """Count rule findings attached to the records in one source import."""
        normalized_ids = {str(record_id).strip() for record_id in record_ids if str(record_id).strip()}
        if not normalized_ids:
            return 0
        with orm_session(self.database_path) as session:
            return int(session.scalar(
                select(func.count(FactQuarantineModel.quarantine_fact_id)).where(
                    FactQuarantineModel.record_id.in_(normalized_ids)
                )
            ) or 0)

    def list_quarantine_findings(self, *, status: str = "OPEN", severity: str = "ALL") -> list[dict]:
        """Return findings enriched for the operational quarantine table.

        ``fact_quarantine`` is the master read model. The original
        ``rule_findings`` row remains available as detailed audit evidence.
        """
        with orm_session(self.database_path) as session:
            query = select(FactQuarantineModel).order_by(FactQuarantineModel.created_at_utc.desc())
            if status != "ALL":
                query = query.where(FactQuarantineModel.status == status)
            if severity != "ALL":
                query = query.where(FactQuarantineModel.severity == severity)

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
                evidence = self._json(finding.evidence_json)
                condition = self._json(version.condition_json) if version is not None else {}
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
            facts = session.scalars(select(FactQuarantineModel).where(FactQuarantineModel.finding_id == finding_id)).all()
            for fact in facts:
                fact.status = status
                fact.updated_at_utc = now
                fact.resolved_by = actor
                fact.resolved_at_utc = now if status in {"RESOLVED", "SUPPRESSED"} else None
            return finding

    @classmethod
    def _create_finding(cls, session, rule, version, record, payload, condition, fingerprint: str, now: str) -> bool:
        if session.scalar(select(RuleFindingModel.finding_id).where(RuleFindingModel.fingerprint == fingerprint)):
            return False
        finding_id = str(uuid.uuid4())
        evidence_json = json.dumps({"record_id": record.record_id, "source_system": record.source_system, "payload": payload}, sort_keys=True)
        session.add(RuleFindingModel(
            finding_id=finding_id, rule_id=rule.rule_id, rule_version_id=version.rule_version_id,
            batch_id=record.batch_id, record_id=record.record_id, worker_id=record.matched_worker_id,
            source_system=record.source_system, severity=version.severity, status="OPEN",
            title=rule.name, message=rule.description or "Business rule matched during ingestion.",
            evidence_json=evidence_json, fingerprint=fingerprint, created_at_utc=now, updated_at_utc=now,
        ))
        cls._create_quarantine_fact(session, finding_id, rule, version, record, payload, condition, evidence_json, now)
        return True

    @staticmethod
    def _create_quarantine_fact(session, finding_id, rule, version, record, payload, condition, evidence_json, now) -> None:
        source = session.scalar(select(DimSourceModel).where(DimSourceModel.source_system == record.source_system))
        field_key = str(condition.get("field") or "")
        field = session.scalar(select(DimFieldModel).where(DimFieldModel.field_key == field_key)) if field_key else None
        expected = condition.get("value", "")
        expected_text = json.dumps(expected, sort_keys=True) if isinstance(expected, (list, dict)) else str(expected or "")
        actual = payload.get(field_key, "") if field_key else ""
        actual_text = json.dumps(actual, sort_keys=True) if isinstance(actual, (list, dict)) else str(actual or "")
        employee_key = record.matched_worker_id if record.matched_worker_id and session.get(DimEmployeeModel, record.matched_worker_id) is not None else None
        session.add(FactQuarantineModel(
            quarantine_fact_id=f"quarantine:{finding_id}", finding_id=finding_id,
            employee_key=employee_key, worker_id=record.matched_worker_id,
            batch_id=record.batch_id, record_id=record.record_id,
            source_id=source.source_id if source is not None else None,
            field_id=field.field_id if field is not None else None,
            source_system=record.source_system, source_record_key=record.source_record_key,
            rule_id=rule.rule_id, rule_version_id=version.rule_version_id,
            field_key=field_key, operator=str(condition.get("operator") or ""),
            expected_value=expected_text, observed_value=actual_text,
            severity=version.severity, status="OPEN", rule_name=rule.name,
            reason=rule.description or "Business rule matched during ingestion.",
            evidence_json=evidence_json, created_at_utc=now, updated_at_utc=now,
        ))

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
        if operator == "contains": return str(expected or "").casefold() in str(actual or "").casefold()
        if operator == "in": return actual in (expected or [])
        return False
