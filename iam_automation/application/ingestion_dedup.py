"""Shared row-level deduplication helpers for source ingestion."""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select

from ..infrastructure.sqlite.orm import DimFieldModel, FactWorkerFieldModel, IngestionRecordModel


def serialize_payload(payload: dict[str, object]) -> str:
    """Return the canonical representation used for row comparisons.

    Empty workbook cells are not persisted in the relational source facts, so
    they must also be omitted from the comparison representation. This keeps a
    reimport of the same row idempotent after its legacy JSON is cleared.
    """
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
        select(IngestionRecordModel.record_id, IngestionRecordModel.source_record_key, IngestionRecordModel.normalized_json, IngestionRecordModel.payload_json)
        .where(
            IngestionRecordModel.source_system == source_system,
            IngestionRecordModel.source_record_key.in_(source_keys),
        )
        .order_by(IngestionRecordModel.created_at_utc.desc())
    ).all()
    latest: dict[str, str] = {}
    latest_rows: dict[str, tuple[str, str]] = {}
    for record_id, source_key, normalized_json, payload_json in rows:
        key = str(source_key)
        if key not in latest_rows:
            latest_rows[key] = (str(record_id), str(normalized_json or payload_json or ""))
    relational: dict[str, dict[str, str]] = {}
    snapshot_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"iam-automation:snapshot:{record_id}")) for record_id, payload in latest_rows.values() if not payload]
    if snapshot_ids:
        for snapshot_id, field_key, value_text in session.execute(
            select(FactWorkerFieldModel.snapshot_id, DimFieldModel.field_key, FactWorkerFieldModel.value_text)
            .join(DimFieldModel, DimFieldModel.field_id == FactWorkerFieldModel.field_id)
            .where(FactWorkerFieldModel.snapshot_id.in_(snapshot_ids))
        ).all():
            relational.setdefault(str(snapshot_id), {})[str(field_key)] = str(value_text or "")
    for key, (record_id, normalized_json) in latest_rows.items():
        if normalized_json:
            latest[key] = payload_digest(normalized_json)
            continue
        snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"iam-automation:snapshot:{record_id}"))
        latest[key] = payload_digest(serialize_payload(relational.get(snapshot_id, {})))
    return latest
