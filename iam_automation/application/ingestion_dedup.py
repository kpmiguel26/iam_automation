"""Shared row-level deduplication helpers for source ingestion."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from ..infrastructure.sqlite.orm import IngestionRecordModel


def serialize_payload(payload: dict[str, object]) -> str:
    """Return the canonical representation used for row comparisons."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


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
        select(IngestionRecordModel.source_record_key, IngestionRecordModel.normalized_json)
        .where(
            IngestionRecordModel.source_system == source_system,
            IngestionRecordModel.source_record_key.in_(source_keys),
        )
        .order_by(IngestionRecordModel.created_at_utc.desc())
    ).all()
    latest: dict[str, str] = {}
    for source_key, normalized_json in rows:
        key = str(source_key)
        if key not in latest:
            latest[key] = payload_digest(str(normalized_json or "{}"))
    return latest
