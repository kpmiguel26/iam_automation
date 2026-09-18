"""Pure tests for the engine-to-engine ingestion contract."""

from __future__ import annotations

import unittest
from pathlib import Path

from iam_automation.application.ingestion.contracts import (
    BatchMetadata,
    FieldMapping,
    IngestionBatch,
    NormalizedRecord,
    RecordMetadata,
)
from iam_automation.application.rules import RuleContext, RulePhase


class IngestionContractTests(unittest.TestCase):
    def test_contract_contains_only_source_neutral_staged_data(self):
        record = NormalizedRecord(
            record_id="record-1",
            source_id="source-1",
            fields={"email": "ada@example.com"},
            metadata=RecordMetadata(row_number=2),
        )
        batch = IngestionBatch(
            batch_id="batch-1",
            source_id="source-1",
            status="STAGED",
            records=(record,),
            field_mappings=(FieldMapping("mapping-1", "email", "field-1", "email", "FACT", "identity", 1),),
            metadata=BatchMetadata(record_count=1),
        )

        self.assertEqual(batch.batch_id, "batch-1")
        self.assertEqual(batch.records[0].fields["email"], "ada@example.com")
        self.assertFalse(hasattr(batch, "path"))
        self.assertFalse(hasattr(record, "reader"))
        self.assertFalse(hasattr(record, "normalizer"))

    def test_contract_rejects_untyped_metadata_bags(self):
        with self.assertRaises(TypeError):
            NormalizedRecord(
                record_id="record-1",
                source_id="source-1",
                fields={},
                metadata={"row_number": 2},
            )
        with self.assertRaises(TypeError):
            IngestionBatch(
                batch_id="batch-1",
                source_id="source-1",
                status="STAGED",
                metadata={"record_count": 1},
            )

    def test_rule_context_has_batch_identity_but_no_source_file_details(self):
        context = RuleContext(phase=RulePhase.BEFORE, database_path=Path("runtime.sqlite"), batch_id="batch-1")

        self.assertEqual(context.batch_id, "batch-1")
        self.assertFalse(hasattr(context, "path"))
        self.assertFalse(hasattr(context, "source_system"))
        self.assertFalse(hasattr(context, "result"))

    def test_rule_context_rejects_untyped_before_results(self):
        with self.assertRaises(TypeError):
            RuleContext(
                phase=RulePhase.AFTER,
                database_path=Path("runtime.sqlite"),
                batch_id="batch-1",
                before_rule_results=({"details": {}},),
            )


if __name__ == "__main__":
    unittest.main()
