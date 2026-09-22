"""Generic staged-evidence contract used by the advisory rule engine.

The rule engine consumes normalized evidence records. Source adapters own file
reading and normalization; this repository only reconstructs values from the
generic ingestion and source-fact tables.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import select

from ..ingestion.contracts import BatchMetadata, FieldMapping, IngestionBatch, NormalizedRecord, RecordMetadata
from ...infrastructure.sqlite.orm import (
    DimFieldModel,
    DimSourceModel,
    FactSourceSnapshotModel,
    FactWorkerFieldModel,
    ImportBatchModel,
    IngestionRecordModel,
    SourceFieldMappingModel,
)


class EvidenceRepository(Protocol):
    """Read-only contract between ingestion persistence and rule evaluation."""

    def batch_for_id(self, session: Any, batch_id: str) -> IngestionBatch | None:
        ...

    def fields_for_record(self, session: Any, record: Any) -> dict[str, str]:
        ...


class SqliteEvidenceRepository:
    """Reconstruct generic evidence from staging and governed field facts."""

    def batch_for_id(self, session: Any, batch_id: str) -> IngestionBatch | None:
        """Materialize the shared ingestion contract from the current store."""
        batch = session.get(ImportBatchModel, str(batch_id))
        if batch is None:
            return None
        source = session.scalar(
            select(DimSourceModel).where(DimSourceModel.source_system == str(batch.source_type or "").upper())
        )
        source_id = str(source.source_id) if source is not None else str(batch.source_type or "")
        records = session.scalars(
            select(IngestionRecordModel)
            .where(
                IngestionRecordModel.batch_id == str(batch_id),
                IngestionRecordModel.status != "QUARANTINED",
            )
            .order_by(IngestionRecordModel.row_number.asc())
        ).all()
        mappings: tuple[FieldMapping, ...] = ()
        if source is not None:
            mappings = tuple(
                FieldMapping(
                    mapping_id=str(mapping_id),
                    source_field_key=str(source_field_key),
                    field_id=str(field_id) if field_id is not None else None,
                    field_key=str(field_key) if field_key is not None else None,
                    target_kind=str(target_kind),
                    transform_name=str(transform_name),
                    mapping_version=int(mapping_version),
                    active=bool(active),
                )
                for mapping_id, source_field_key, field_id, field_key, target_kind, transform_name, mapping_version, active in session.execute(
                    select(
                        SourceFieldMappingModel.mapping_id,
                        SourceFieldMappingModel.source_field_key,
                        SourceFieldMappingModel.field_id,
                        DimFieldModel.field_key,
                        SourceFieldMappingModel.target_kind,
                        SourceFieldMappingModel.transform_name,
                        SourceFieldMappingModel.mapping_version,
                        SourceFieldMappingModel.active,
                    ).join(
                        DimFieldModel,
                        DimFieldModel.field_id == SourceFieldMappingModel.field_id,
                        isouter=True,
                    ).where(SourceFieldMappingModel.source_id == source.source_id)
                ).all()
            )
        normalized_records = tuple(
            NormalizedRecord(
                record_id=str(record.record_id),
                source_id=source_id,
                fields=self.fields_for_record(session, record),
                metadata=RecordMetadata(
                    source_record_key=str(record.source_record_key),
                    row_number=int(record.row_number or 0),
                    status=str(record.status or ""),
                ),
            )
            for record in records
        )
        return IngestionBatch(
            batch_id=str(batch.batch_id),
            source_id=source_id,
            status=str(batch.status or ""),
            records=normalized_records,
            field_mappings=mappings,
            metadata=BatchMetadata(record_count=len(normalized_records)),
        )

    def fields_for_record(self, session: Any, record: Any) -> dict[str, str]:
        """Return governed fields without consulting a source-specific model."""
        snapshot = session.scalar(
            select(FactSourceSnapshotModel)
            .join(DimSourceModel, DimSourceModel.source_id == FactSourceSnapshotModel.source_id)
            .where(
                FactSourceSnapshotModel.batch_id == record.batch_id,
                FactSourceSnapshotModel.source_record_key == record.source_record_key,
                DimSourceModel.source_system == record.source_system,
            )
        )
        if snapshot is not None:
            rows = session.execute(
                select(DimFieldModel.field_key, FactWorkerFieldModel.value_text)
                .join(FactWorkerFieldModel, FactWorkerFieldModel.field_id == DimFieldModel.field_id)
                .where(FactWorkerFieldModel.snapshot_id == snapshot.snapshot_id)
            ).all()
            payload: dict[str, str] = {}
            previous = session.scalar(
                select(IngestionRecordModel)
                .where(
                    IngestionRecordModel.source_system == record.source_system,
                    IngestionRecordModel.source_record_key == record.source_record_key,
                    IngestionRecordModel.record_id != record.record_id,
                    IngestionRecordModel.status != "QUARANTINED",
                    IngestionRecordModel.created_at_utc < record.created_at_utc,
                )
                .order_by(IngestionRecordModel.created_at_utc.desc())
            )
            if previous is not None:
                payload.update(self.fields_for_record(session, previous))
            payload.update({str(field_key): str(value or "") for field_key, value in rows})
            if payload:
                return payload

        raw = record.normalized_json or record.payload_json or "{}"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return {str(key): str(value or "") for key, value in parsed.items()} if isinstance(parsed, dict) else {}
