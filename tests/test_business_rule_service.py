"""Regression tests for advisory, post-import business rule evaluation."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from iam_automation.application.business_rule_service import BusinessRuleService
from iam_automation.application.star_schema_writer import StarSchemaWriter
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    IngestionRecordModel,
    ImportBatchModel,
    FactWorkerFieldModel,
    RuleFindingModel,
    orm_session,
)


class BusinessRuleServiceTests(unittest.TestCase):
    def _relational_batch(self, database):
        with orm_session(database) as session:
            session.add(ImportBatchModel(batch_id="relational", filename="source.xlsx", source_type="MASTER_ROSTER", status="COMPLETED", total_rows=2, valid_rows=2, created_by="test"))
            for number, email in enumerate(("ada@example.com", ""), start=1):
                session.add(IngestionRecordModel(
                    record_id=f"record-{number}", batch_id="relational",
                    source_system="MASTER_ROSTER", source_file="source.xlsx",
                    source_checksum="checksum", row_number=number,
                    source_record_key=f"E-{number}",
                    normalized_json=json.dumps({"email": email, "status": "TERMINATED"}),
                    payload_json="{}",
                ))
            StarSchemaWriter.write_batch_in_session(session, "relational")
        StarSchemaWriter.clear_legacy_payloads(database, "relational")

    def _active_rule(self, service, *, field="status", operator="equals", value="TERMINATED"):
        rule_id = service.create_rule(name=f"Review {field}", description="Review source evidence", field=field, operator=operator, value=value, severity="WARNING", actor="test")
        service.set_status(rule_id, "ACTIVE")
        return rule_id

    def test_relational_rules_after_json_cleanup_include_evidence_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            self._active_rule(service)
            with orm_session(database) as session:
                for record in session.query(IngestionRecordModel).all():
                    self.assertEqual(record.normalized_json, "")
                    self.assertEqual(record.payload_json, "")
            self.assertEqual(service.evaluate_all_batches(), 2)
            self.assertEqual(service.evaluate_all_batches(), 0)
            findings = service.list_findings()
            self.assertEqual(len(findings), 2)
            for finding in findings:
                evidence = json.loads(finding.evidence_json)
                self.assertEqual(evidence["payload"]["status"], "TERMINATED")
                self.assertEqual(evidence["record_id"], finding.record_id)

    def test_relational_missing_rule_does_not_flag_populated_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            self._active_rule(service, field="email", operator="missing", value="")
            self.assertEqual(service.evaluate_batch("relational"), 1)
            self.assertEqual(service.list_findings()[0].record_id, "record-2")

    def test_relational_facts_take_precedence_over_stale_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            with orm_session(database) as session:
                for record in session.query(IngestionRecordModel).all():
                    record.normalized_json = json.dumps({"status": "ACTIVE"})
            service = BusinessRuleService(database)
            self._active_rule(service)
            self.assertEqual(service.evaluate_batch("relational"), 2)

    def test_failed_evaluation_rolls_back_findings_and_preserves_import_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            self._active_rule(service)
            with orm_session(database) as session:
                fact_count = session.query(FactWorkerFieldModel).count()
            with patch.object(service, "_matches", side_effect=[True, RuntimeError("evaluation failed")]):
                with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
                    service.evaluate_batch("relational")
            with orm_session(database) as session:
                self.assertEqual(session.query(RuleFindingModel).count(), 0)
                self.assertEqual(session.get(ImportBatchModel, "relational").status, "COMPLETED")
                self.assertEqual(session.query(FactWorkerFieldModel).count(), fact_count)
                self.assertEqual(session.query(IngestionRecordModel).count(), 2)
            self.assertEqual(service.evaluate_batch("relational"), 2)

    def test_active_rule_creates_idempotent_finding_after_batch_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(database) as session:
                session.add(BusinessRuleModel(rule_id="rule-1", name="Missing email", description="Email requires review.", status="ACTIVE", current_version=1, created_at_utc=now, updated_at_utc=now))
                session.add(BusinessRuleVersionModel(rule_version_id="rule-1-v1", rule_id="rule-1", version=1, scope_json="{}", condition_json=json.dumps({"field": "email", "operator": "missing"}), severity="WARNING", status="ACTIVE", created_at_utc=now))
                session.add(IngestionRecordModel(record_id=str(uuid.uuid4()), batch_id="batch-1", source_system="ROSTER_LOCK", source_file="x.xlsx", source_checksum="checksum", row_number=1, source_record_key="worker-1", normalized_json=json.dumps({"name": "A"}), payload_json="{}", created_at_utc=now))

            service = BusinessRuleService(database)
            self.assertEqual(service.evaluate_batch("batch-1"), 1)
            self.assertEqual(service.evaluate_batch("batch-1"), 0)
            self.assertEqual(service.summary()["open"], 1)
            with orm_session(database) as session:
                self.assertEqual(session.query(RuleFindingModel).count(), 1)

    def test_activation_evaluates_existing_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(database) as session:
                session.add(BusinessRuleModel(rule_id="rule-2", name="Terminated review", status="ACTIVE", current_version=1, created_at_utc=now, updated_at_utc=now))
                session.add(BusinessRuleVersionModel(rule_version_id="rule-2-v1", rule_id="rule-2", version=1, condition_json=json.dumps({"field": "status", "operator": "equals", "value": "TERMINATED"}), scope_json="{}", status="ACTIVE", created_at_utc=now))
                session.add(IngestionRecordModel(record_id=str(uuid.uuid4()), batch_id="batch-old", source_system="MASTER_ROSTER", source_file="x.xlsx", source_checksum="checksum", row_number=1, source_record_key="worker-2", normalized_json=json.dumps({"status": "TERMINATED"}), payload_json="{}", created_at_utc=now))
            self.assertEqual(BusinessRuleService(database).evaluate_all_batches(), 1)
            self.assertEqual(BusinessRuleService(database).summary()["open"], 1)


if __name__ == "__main__":
    unittest.main()
