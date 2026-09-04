"""Regression tests for advisory, post-import business rule evaluation."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from iam_automation.application.business_rule_service import BusinessRuleService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    BusinessRuleModel,
    BusinessRuleVersionModel,
    IngestionRecordModel,
    RuleFindingModel,
    orm_session,
)


class BusinessRuleServiceTests(unittest.TestCase):
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
