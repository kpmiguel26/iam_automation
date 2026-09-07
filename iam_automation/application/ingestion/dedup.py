"""Shared row-level deduplication helpers for source ingestion."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from ...infrastructure.sqlite.orm import IngestionRecordModel


def serialize_payload(payload: dict[str, object]) -> str:
    """Return the canonical representation used for row comparisons."""
    compact = {
        str(key): str(value).strip()
        for key, value in payload.items()
        if str(value or "").strip()
    }
    return json.dumps(compact, sort_keys=True, separators=(",", ":"), default=str)


def payload_digest(normalized_json: str) -> str:
    try:
        canonical = serialize_payload(json.loads(normalized_json or "{}"))
    except (TypeError, json.JSONDecodeError):
        canonical = normalized_json
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def latest_payload_digests(session, source_system: str, source_keys: set[str]) -> dict[str, str]:
    """Load the latest observed payload for each source key in one query."""
    if not source_keys:
        return {}
    rows = session.execute(
        select(
            IngestionRecordModel.record_id,
            IngestionRecordModel.source_record_key,
            IngestionRecordModel.normalized_json,
            IngestionRecordModel.payload_json,
        )
        .where(
            IngestionRecordModel.source_system == source_system,
            IngestionRecordModel.source_record_key.in_(source_keys),
        )
        .order_by(IngestionRecordModel.created_at_utc.desc())
    ).all()
    latest_rows: dict[str, str] = {}
    for record_id, source_key, _normalized_json, _payload_json in rows:
        key = str(source_key)
        if key not in latest_rows:
            latest_rows[key] = str(record_id)

    # Import lazily to avoid a module cycle. payload_for_record merges delta
    # facts with the previous source observation before hashing the row.
    from ..star_schema_writer import StarSchemaWriter

    latest: dict[str, str] = {}
    for key, record_id in latest_rows.items():
        record = session.get(IngestionRecordModel, record_id)
        latest[key] = payload_digest(serialize_payload(StarSchemaWriter.payload_for_record(session, record)))
    return latest
