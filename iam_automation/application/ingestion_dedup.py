"""Compatibility facade for shared ingestion deduplication helpers."""

from .ingestion.dedup import latest_payload_digests, payload_digest, serialize_payload

__all__ = ["latest_payload_digests", "payload_digest", "serialize_payload"]
