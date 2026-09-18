"""Integration coverage for the generic ingestion-to-rules boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.business_rule_service import BusinessRuleService
from iam_automation.application.ingestion.contracts import (
    BatchMetadata,
    FieldMapping,
    IngestionBatch,
    NormalizedRecord,
    RecordMetadata,
)
from iam_automation.application.rules.execution import RuleExecutionService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    ImportBatchModel,
    IngestionRecordModel,
    orm_session,
)


class _GenericBatchProducer:
    def __init__(self, batch: IngestionBatch):
        self.batch = batch

    def produce(self) -> IngestionBatch:
        return self.batch


class _GenericEvidenceRepository:
    """Test producer/consumer bridge with no adapter or source labels."""

    def __init__(self, producer: _GenericBatchProducer):
        self.producer = producer

    def batch_for_id(self, session, batch_id: str) -> IngestionBatch | None:
        batch = self.producer.produce()
        return batch if batch.batch_id == batch_id else None

    def fields_for_record(self, session, record) -> dict[str, str]:
        return {"status": "TERMINATED"} if record.record_id == "record-1" else {}


class RulesIngestionBoundaryTests(unittest.TestCase):
    def test_rules_consume_only_the_generic_batch_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(ImportBatchModel(
                    batch_id="batch-generic",
                    filename="producer-owned",
                    source_type="ROSTER_LOCK",
                    status="STAGED",
                    total_rows=1,
                    valid_rows=1,
                    created_by="test",
                ))
                session.add(IngestionRecordModel(
                    record_id="record-1",
                    batch_id="batch-generic",
                    source_system="ROSTER_LOCK",
                    source_file="producer-owned",
                    source_checksum="checksum",
                    row_number=2,
                    source_record_key="E-1",
                    normalized_json="{}",
                    payload_json="{}",
                    status="STAGED",
                ))

            service = BusinessRuleService(database)
            rule_id = service.create_rule(
                name="Generic status review",
                description="Review terminated records.",
                field="status",
                operator="equals",
                value="TERMINATED",
                severity="WARNING",
                actor="test",
            )
            service.set_status(rule_id, "ACTIVE")

            batch = IngestionBatch(
                batch_id="batch-generic",
                source_id="producer-source-1",
                status="STAGED",
                records=(NormalizedRecord(
                    record_id="record-1",
                    source_id="producer-source-1",
                    fields={"status": "TERMINATED"},
                    metadata=RecordMetadata(source_record_key="E-1", row_number=2, status="STAGED"),
                ),),
                field_mappings=(FieldMapping(
                    mapping_id="mapping-1",
                    source_field_key="status_column",
                    field_id=None,
                    field_key="status",
                    target_kind="FACT",
                    transform_name="identity",
                    mapping_version=1,
                ),),
                metadata=BatchMetadata(record_count=1),
            )
            service._execution = RuleExecutionService(
                service,
                _GenericEvidenceRepository(_GenericBatchProducer(batch)),
            )

            self.assertEqual(service.evaluate_batch("batch-generic"), 1)
            findings = service.list_findings()
            self.assertEqual(len(findings), 1)
            self.assertEqual(json.loads(findings[0].evidence_json)["payload"]["status"], "TERMINATED")


if __name__ == "__main__":
    unittest.main()
