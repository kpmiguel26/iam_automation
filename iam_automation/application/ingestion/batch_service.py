"""Generic batch lifecycle coordination for source ingestion."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ...infrastructure.sqlite.orm import (
    ImportBatchModel,
    IngestionRecordModel,
    QuarantineRecordModel,
    orm_session,
)
from ...infrastructure.sqlite.star_schema_writer import StarSchemaWriter
from .contracts import IngestionBatchOutcome, IngestionRecordInput
from .dedup import latest_payload_digests, payload_digest, serialize_payload


class IngestionBatchService:
    """Own generic batch persistence without owning source policy or rules."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def persist_rows(
        self,
        *,
        source_system: str,
        filename: str,
        source_file: str,
        source_checksum: str,
        source_modified_at_utc: str = "",
        created_by: str = "workspace-watcher",
        total_rows: int,
        rows: Iterable[IngestionRecordInput],
        validate_row: Callable[[IngestionRecordInput, set[str]], str | None] | None = None,
    ) -> IngestionBatchOutcome:
        """Persist staged/quarantined rows and commit one complete batch.

        Reader and normalization happen before this method. A source-specific
        validator may be supplied as a callback so validation, deduplication and
        the existing source-key ordering remain inside one generic lifecycle.
        The lifecycle owns persistence coordination, fact writing, counters and
        the commit boundary; it does not own source policy.
        """
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        row_inputs = tuple(rows)
        staged = quarantined = duplicates = 0
        seen_keys: set[str] = set()

        with orm_session(self.database_path) as session:
            session.add(
                ImportBatchModel(
                    batch_id=batch_id,
                    filename=filename,
                    source_type=source_system,
                    status="PROCESSING",
                    total_rows=total_rows,
                    valid_rows=0,
                    quarantine_rows=0,
                    created_by=created_by,
                    created_at_utc=now,
                    source_modified_at_utc=source_modified_at_utc,
                )
            )
            existing_payloads = latest_payload_digests(
                session,
                source_system,
                {row.source_record_key for row in row_inputs},
            )
            for row in row_inputs:
                validation_error = (
                    validate_row(row, seen_keys)
                    if validate_row is not None
                    else row.validation_error
                )
                if validation_error:
                    quarantined += 1
                    session.add(
                        QuarantineRecordModel(
                            quarantine_id=str(uuid.uuid4()),
                            batch_id=batch_id,
                            row_number=row.row_number,
                            reason=validation_error,
                            payload_json=json.dumps(dict(row.source_fields), sort_keys=True),
                            status="OPEN",
                            created_at_utc=now,
                        )
                    )
                    continue

                normalized_json = serialize_payload(dict(row.normalized_fields))
                if existing_payloads.get(row.source_record_key) == payload_digest(normalized_json):
                    duplicates += 1
                    continue
                seen_keys.add(row.source_record_key)
                staged += 1
                session.add(
                    IngestionRecordModel(
                        record_id=str(uuid.uuid4()),
                        batch_id=batch_id,
                        source_system=source_system,
                        source_file=source_file,
                        source_checksum=source_checksum,
                        row_number=row.row_number,
                        source_record_key=row.source_record_key,
                        normalized_json=normalized_json,
                        payload_json=json.dumps(dict(row.source_fields), sort_keys=True),
                        status="STAGED",
                        created_at_utc=now,
                    )
                )

            StarSchemaWriter.write_batch_in_session(session, batch_id, now)
            batch = session.get(ImportBatchModel, batch_id)
            status = "COMPLETED" if quarantined == 0 else "COMPLETED_WITH_WARNINGS"
            batch.valid_rows = staged
            batch.quarantine_rows = quarantined
            batch.status = status
            batch.completed_at_utc = datetime.now(timezone.utc).isoformat()

        # Preserve the existing post-commit cleanup boundary. It is idempotent
        # and remains outside the source/fact transaction during this slice.
        StarSchemaWriter.clear_legacy_payloads(self.database_path, batch_id)
        return IngestionBatchOutcome(
            batch_id=batch_id,
            filename=filename,
            total_rows=total_rows,
            staged_rows=staged,
            quarantine_rows=quarantined,
            duplicate_rows=duplicates,
            status=status,
        )
