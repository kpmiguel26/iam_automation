"""Regression tests for advisory, post-import business rule evaluation."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.datastructures import MultiDict

from iam_automation.application.business_rule_service import BusinessRuleService
from iam_automation.application.ingestion.orchestrator import IngestionOrchestrator
from iam_automation.application.star_schema_writer import StarSchemaWriter
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    IngestionRecordModel,
    ImportBatchModel,
    FactWorkerFieldModel,
    FactQuarantineModel,
    RuleFindingModel,
    SourceFieldMappingModel,
    WorkerModel,
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

    def _active_rule(self, service, *, field="status", operator="equals", value="TERMINATED", source_system="ALL"):
        rule_id = service.create_rule(name=f"Review {field}", description="Review source evidence", field=field, operator=operator, value=value, severity="WARNING", source_system=source_system, actor="test")
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
            with orm_session(database) as session:
                self.assertEqual(session.query(FactQuarantineModel).count(), 2)
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

    def test_quarantine_projection_includes_rule_employee_and_affected_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(database) as session:
                session.add(ImportBatchModel(batch_id="quarantine", filename="source.xlsx", source_type="MASTER_ROSTER", status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now))
                session.add(WorkerModel(worker_id="worker-1", first_name="Ada", last_name="Lovelace", display_name="Ada Lovelace", canonical_email="ada@example.com", status="ACTIVE", created_at_utc=now, updated_at_utc=now))
                session.add(IngestionRecordModel(record_id="record-q", batch_id="quarantine", source_system="MASTER_ROSTER", source_file="source.xlsx", source_checksum="checksum", row_number=4, source_record_key="E-4", normalized_json=json.dumps({"status": "TERMINATED"}), payload_json="{}", matched_worker_id="worker-1", created_at_utc=now))
            service = BusinessRuleService(database)
            self._active_rule(service)
            self.assertEqual(service.evaluate_batch("quarantine"), 1)
            item = service.list_quarantine_findings()[0]
            self.assertEqual(item["rule_name"], "Review status")
            self.assertEqual(item["employee"]["name"], "Ada Lovelace")
            self.assertEqual(item["employee"]["email"], "ada@example.com")
            self.assertEqual(item["field"], "status")
            self.assertEqual(item["actual_value"], "TERMINATED")
            self.assertEqual(service.count_findings_for_records(["record-q"]), 1)
            self.assertEqual(service.count_findings_for_records(["other-record"]), 0)

    def test_quarantine_findings_can_be_filtered_by_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            status_rule = self._active_rule(service)
            email_rule = self._active_rule(service, field="email", operator="missing", value="")
            self.assertEqual(service.evaluate_batch("relational"), 3)
            filtered = service.list_quarantine_findings(status="ALL", rule_id=email_rule)
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["finding"].rule_id, email_rule)
            self.assertNotEqual(filtered[0]["finding"].rule_id, status_rule)

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
                session.add(ImportBatchModel(batch_id="batch-1", filename="x.xlsx", source_type="ROSTER_LOCK", status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now))
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
                session.add(ImportBatchModel(batch_id="batch-old", filename="x.xlsx", source_type="MASTER_ROSTER", status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now))
                session.add(BusinessRuleModel(rule_id="rule-2", name="Terminated review", status="ACTIVE", current_version=1, created_at_utc=now, updated_at_utc=now))
                session.add(BusinessRuleVersionModel(rule_version_id="rule-2-v1", rule_id="rule-2", version=1, condition_json=json.dumps({"field": "status", "operator": "equals", "value": "TERMINATED"}), scope_json="{}", status="ACTIVE", created_at_utc=now))
                session.add(IngestionRecordModel(record_id=str(uuid.uuid4()), batch_id="batch-old", source_system="MASTER_ROSTER", source_file="x.xlsx", source_checksum="checksum", row_number=1, source_record_key="worker-2", normalized_json=json.dumps({"status": "TERMINATED"}), payload_json="{}", created_at_utc=now))
            self.assertEqual(BusinessRuleService(database).evaluate_all_batches(), 1)
            self.assertEqual(BusinessRuleService(database).summary()["open"], 1)

    def test_rule_phase_is_persisted_and_exposed_to_the_guided_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = BusinessRuleService(database)
            service.create_rule(name="Preflight check", description="Validate source", field="email", operator="exists", value="", severity="INFO", phase="BEFORE", actor="test")
            listed = service.list_rules()
            self.assertEqual(listed[0]["execution_phase"], "BEFORE")
            self.assertIn("email", service.available_fields())

    def test_rule_registry_exposes_user_friendly_condition_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = BusinessRuleService(database)
            service.create_rule(
                name="Missing employee email", description="Ask the reviewer to confirm the contact address.",
                field="email", operator="missing", value="", severity="WARNING", actor="test",
            )

            item = service.list_rules()[0]

            self.assertEqual(item["condition_display"], "Email is missing")
            self.assertEqual(item["severity_label"], "Needs review")
            self.assertEqual(item["phase_label"], "After import")
            self.assertEqual(item["status_label"], "Draft")

    def test_observed_source_fields_extend_rule_catalog_without_hardcoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(database) as session:
                session.add(ImportBatchModel(
                    batch_id="dynamic-roster", filename="roster.xlsx", source_type="ROSTER_LOCK",
                    status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now,
                ))
                session.add(IngestionRecordModel(
                    record_id="dynamic-roster-record", batch_id="dynamic-roster",
                    source_system="ROSTER_LOCK", source_file="roster.xlsx", source_checksum="dynamic",
                    row_number=1, source_record_key="E-100", normalized_json=json.dumps({
                        "vendor_employee_id": "E-100",
                        "future_review_flag": "REVIEW",
                        "empty_but_present_column": "",
                    }), payload_json="{}", created_at_utc=now,
                ))
                StarSchemaWriter.write_batch_in_session(session, "dynamic-roster", now=now)

            service = BusinessRuleService(database)
            roster_fields = service.available_fields("ROSTER_LOCK")
            self.assertIn("future_review_flag", roster_fields)
            self.assertIn("empty_but_present_column", roster_fields)

            rule_id = service.create_rule(
                name="Future review flag", description="Review a newly detected source field.",
                field="future_review_flag", operator="equals", value="REVIEW",
                severity="WARNING", source_system="ROSTER_LOCK", actor="test",
            )
            self.assertTrue(rule_id)
            with orm_session(database) as session:
                mapping = session.query(SourceFieldMappingModel).filter_by(
                    source_field_key="future_review_flag",
                ).one()
                self.assertTrue(mapping.active)

    def test_before_rule_is_evaluated_before_adapter_and_persisted_after_batch_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            workbook_path = root / "roster.xlsx"
            from openpyxl import Workbook
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Vendor Name", "Vendor employee ID", "Employee email"])
            sheet.append(["TTEC", "E-100", ""])
            workbook.save(workbook_path)

            service = BusinessRuleService(database)
            rule_id = service.create_rule(name="Email preflight", description="Review missing email.", field="email", operator="missing", value="", severity="WARNING", phase="BEFORE", source_system="ROSTER_LOCK", actor="test")
            service.set_status(rule_id, "ACTIVE")

            result = IngestionOrchestrator(database).ingest_file("ROSTER_LOCK", workbook_path, actor="test")

            with orm_session(database) as session:
                fact = session.query(FactQuarantineModel).one()
                self.assertEqual(fact.rule_id, rule_id)
                self.assertEqual(fact.batch_id, result.batch_id)
                self.assertEqual(session.query(RuleFindingModel).count(), 1)

    def test_contains_rule_is_scoped_to_selected_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(database) as session:
                session.add(ImportBatchModel(batch_id="master-batch", filename="master.xlsx", source_type="MASTER_ROSTER", status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now))
                session.add(ImportBatchModel(batch_id="roster-batch", filename="roster.xlsx", source_type="ROSTER_LOCK", status="COMPLETED", total_rows=1, valid_rows=1, created_by="test", created_at_utc=now))
                session.add(IngestionRecordModel(record_id="master-record", batch_id="master-batch", source_system="MASTER_ROSTER", source_file="master.xlsx", source_checksum="master", row_number=1, source_record_key="M-1", normalized_json=json.dumps({"npn_login_id": "123|RECORD|456"}), payload_json="{}", created_at_utc=now))
                session.add(IngestionRecordModel(record_id="roster-record", batch_id="roster-batch", source_system="ROSTER_LOCK", source_file="roster.xlsx", source_checksum="roster", row_number=1, source_record_key="R-1", normalized_json=json.dumps({"npn_login_id": "123|RECORD|456"}), payload_json="{}", created_at_utc=now))
            service = BusinessRuleService(database)
            self._active_rule(service, field="npn_login_id", operator="contains", value="|RECORD|", source_system="MASTER_ROSTER")
            self.assertEqual(service.evaluate_batch("master-batch"), 1)
            self.assertEqual(service.evaluate_batch("roster-batch"), 0)
            self.assertEqual(service.list_rules()[0]["source_system"], "MASTER_ROSTER")
            self.assertIn("npn_login_id", service.available_fields("MASTER_ROSTER"))
            self.assertNotIn("vendor_employee_id", service.available_fields("MASTER_ROSTER"))

    def test_delete_rule_removes_versions_findings_and_quarantine_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            rule_id = self._active_rule(service)
            self.assertEqual(service.evaluate_batch("relational"), 2)

            deleted = service.delete_rule(rule_id)

            self.assertEqual(deleted["rule"], 1)
            self.assertEqual(deleted["versions"], 1)
            self.assertEqual(deleted["findings"], 2)
            self.assertEqual(deleted["quarantine_facts"], 2)
            with orm_session(database) as session:
                self.assertIsNone(session.get(BusinessRuleModel, rule_id))
                self.assertEqual(session.query(BusinessRuleVersionModel).filter_by(rule_id=rule_id).count(), 0)
                self.assertEqual(session.query(RuleFindingModel).filter_by(rule_id=rule_id).count(), 0)
                self.assertEqual(session.query(FactQuarantineModel).filter_by(rule_id=rule_id).count(), 0)

    def test_after_evaluation_ignores_a_batch_removed_by_testing_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = BusinessRuleService(database)
            self.assertEqual(service.evaluate_batch("missing-batch"), 0)

    def test_complex_rule_is_persisted_and_evaluated_against_pinned_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            rule_id = service.create_complex_rule(
                name="Status requires review",
                description="Review terminated source evidence.",
                condition={
                    "all": [{
                        "left": {"kind": "field", "field": "status"},
                        "operator": "equals",
                        "right": {"kind": "literal", "value": "TERMINATED"},
                    }]
                },
                severity="WARNING",
                actor="test",
            )
            with orm_session(database) as session:
                version = session.query(BusinessRuleVersionModel).filter_by(rule_id=rule_id).one()
                self.assertEqual(version.context_version_id, "context:default:1")
            service.set_status(rule_id, "ACTIVE")
            self.assertEqual(service.evaluate_batch("relational"), 2)
            self.assertEqual(service.list_rules()[0]["condition_display"], "Status equals 'TERMINATED'")

    def test_explicit_condition_form_builds_rehire_shape_without_business_rule_template(self):
        values = MultiDict([
            ("condition_group", "all"),
            ("condition_left_kind", "field"), ("condition_left_kind", "derived"),
            ("condition_left_source", "ACCESSNOW"), ("condition_left_source", "ACCESSNOW"),
            ("condition_left_field", "accessnow_status"), ("condition_left_field", ""),
            ("condition_left_value", ""), ("condition_left_value", ""),
            ("condition_left_function", "business_days_between"), ("condition_left_function", "business_days_between"),
            ("condition_left_arg1_kind", "field"), ("condition_left_arg1_kind", "field"),
            ("condition_left_arg1_source", "ACCESSNOW"), ("condition_left_arg1_source", "ACCESSNOW"),
            ("condition_left_arg1_field", ""), ("condition_left_arg1_field", "termination_date"),
            ("condition_left_arg1_value", ""), ("condition_left_arg1_value", ""),
            ("condition_left_arg2_kind", "field"), ("condition_left_arg2_kind", "field"),
            ("condition_left_arg2_source", "ACCESSNOW"), ("condition_left_arg2_source", "ROSTER_LOCK"),
            ("condition_left_arg2_field", ""), ("condition_left_arg2_field", "onboarding_date"),
            ("condition_left_arg2_value", ""), ("condition_left_arg2_value", ""),
            ("condition_operator", "in"), ("condition_operator", "between"),
            ("condition_right_kind", "literal"), ("condition_right_kind", "literal"),
            ("condition_right_source", "ACCESSNOW"), ("condition_right_source", "ACCESSNOW"),
            ("condition_right_field", ""), ("condition_right_field", ""),
            ("condition_right_value", "TERMINATED,DEACTIVATED"), ("condition_right_value", "0,30"),
        ])

        condition = BusinessRuleService.condition_from_form(values)

        self.assertEqual(condition["all"][0]["right"]["value"], ["TERMINATED", "DEACTIVATED"])
        self.assertEqual(condition["all"][1]["left"]["function"], "business_days_between")
        self.assertEqual(condition["all"][1]["left"]["arguments"][1]["source"], "ROSTER_LOCK")
        self.assertEqual(condition["all"][1]["right"]["value"], ["0", "30"])

    def test_rule_test_preview_does_not_create_findings_or_change_draft_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self._relational_batch(database)
            service = BusinessRuleService(database)
            rule_id = self._active_rule(service)
            service.set_status(rule_id, "DISABLED")
            with orm_session(database) as session:
                rule = session.get(BusinessRuleModel, rule_id)
                rule.status = "DRAFT"
                version = session.query(BusinessRuleVersionModel).filter_by(rule_id=rule_id).one()
                version.status = "DRAFT"

            result = service.test_rule(rule_id)

            self.assertEqual(result["match_count"], 2)
            self.assertEqual(result["evaluated"], 2)
            self.assertEqual(result["rule_status"], "DRAFT")
            self.assertEqual(service.list_findings(status="ALL"), [])
            with orm_session(database) as session:
                self.assertEqual(session.get(BusinessRuleModel, rule_id).status, "DRAFT")


if __name__ == "__main__":
    unittest.main()
