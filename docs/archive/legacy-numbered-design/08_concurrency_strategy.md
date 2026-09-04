# Concurrency Strategy

The architecture uses:

- Single-writer operational control for publication.
- Idempotent `request_id` processing.
- Optimistic concurrency on mutable business records.
- Published snapshot version/checksum comparison before publish.

When applying a request, the update must include `RecordVersion = expected_record_version`. If zero rows update, mark the request `CONFLICT` and do not overwrite.
