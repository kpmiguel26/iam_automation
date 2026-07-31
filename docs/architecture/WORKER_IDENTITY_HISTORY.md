# Worker Identity History

## Purpose

The canonical employee is a stable worker profile. Source files are evidence,
not the employee record itself. Roster Lock, Fieldglass/RSR and future sources
can enrich the same worker without replacing its identity or deleting history.

## SQLite model

- `workers` stores the current canonical profile and its `record_version`.
- `worker_identifiers` stores source-specific IDs such as vendor ID, Fieldglass
  ID and NUID.
- `worker_engagements` stores vendor/project assignments and rehires.
- `worker_source_lineage` stores the source file, checksum, row and field that
  produced each value.
- `worker_profile_versions` stores immutable JSON snapshots. The unique key is
  `(worker_id, version_number)`.
- `worker_merge_events` records duplicate resolution without deleting either
  worker row.

## Version behavior

Migration `v006_worker_history` creates the history tables and the
`superseded_by_worker_id` marker. On runtime initialization, existing workers
without history receive an idempotent `BASELINE_BACKFILL` version 1. Future
promotions, enrichments and merges append versions with source metadata and
changed fields.

Previous versions are available from the employee profile at:

```text
/employees/<worker_id>/history
```

The SQLite schema revision is stored in `alembic_version` and is shown in
Database administration, for example `0006_worker_history`. Schema revisions
and employee profile versions are separate: employee history is stored in
`worker_profile_versions` with a monotonic `version_number` per worker.

The history page is read-only and shows the version number, change type, actor,
source file/checksum and the complete JSON snapshot used for audit and review.

## Duplicate handling

Matching prioritizes active source identifiers, then case-insensitive canonical
email and finally case-insensitive first/last name. Superseded workers are
excluded from new matches and the active directory. A merge moves related
identifiers, engagements, lineage and discrepancies to the survivor, marks the
duplicate as `DUPLICATE_SUPERSEDED`, and records a merge event plus snapshots
for both records. No worker row or source evidence is physically deleted.

Ambiguous matches remain pending for administrative review. The system never
silently merges a record when multiple canonical workers match.
