# Work Tracking - Worker Identity History

> **Historical record — 2026-07-31.** Current status is maintained only in
> [`../../../STATUS.md`](../../../STATUS.md).

## Objective

Keep one canonical employee profile while preserving every approved change,
source observation, duplicate resolution and rehire as historical evidence in
SQLite.

## Completed

- Created feature branch `feature/worker-identity-history`.
- Added Alembic migration `0006_worker_history`.
- Added `worker_profile_versions` for immutable employee snapshots.
- Added `worker_merge_events` and `superseded_by_worker_id` for duplicate handling.
- Added idempotent baseline versioning for employees already in SQLite.
- Added version recording for promotions, enrichments and merges.
- Excluded superseded profiles from the active employee directory.
- Added employee history page: `/employees/<worker_id>/history`.
- Added SQLite schema revision visibility in Database administration.
- Added tests for migration state, baseline backfill, append-only versions and duplicate merges.
- Changed watcher and source-request approval to a review-only gate: no canonical
  employee is created or enriched automatically when a source file or import
  request is approved.
- Added idempotent administrator alerts for source updates waiting at
  `/employees/source-updates`.
- Added an Updates attention badge to the Employees directory.
- Reset local and simulated runtime SQLite derived data for a clean source-update
  review test; application users and roles were preserved.

## Review Rules

- `worker_id` is immutable and remains the canonical identity.
- A rehire creates a new engagement; it does not create a second worker.
- Source identifiers are matched only against active, non-superseded workers.
- Ambiguous matches remain reviewable and are never silently merged.
- Original source lineage remains unchanged.
- Duplicate workers are retained as historical records and marked as superseded.

## How To Review Versions

The current SQLite schema revision is stored in `alembic_version` and appears
in Database administration. Employee profile history is stored in
`worker_profile_versions` and appears in each employee profile under **View
previous versions**.

Example direct SQLite checks:

```sql
SELECT version_num FROM alembic_version;

SELECT worker_id, version_number, change_type, source_system, actor, created_at_utc
FROM worker_profile_versions
ORDER BY worker_id, version_number;

SELECT duplicate_worker_id, survivor_worker_id, reason, merged_by, merged_at_utc
FROM worker_merge_events
ORDER BY merged_at_utc DESC;
```

## Verification

- Targeted ingestion, employee-domain and workspace-refresh tests: **11 tests passed**.
- Full suite: **90 tests passed, 1 environment-restricted Waitress smoke test**.
  The remaining failure occurs when this sandbox denies binding an ephemeral
  loopback socket; it is not a functional assertion failure.

## Pending

- Review real Fieldglass and Roster Lock matching rules with stakeholders.
- Define the final merge approval policy for ambiguous duplicate candidates.
- Add operational reports for duplicate clusters and unresolved discrepancies.
- Integrate the finalized history model with selective source-update review UI.
- Define the final notification retention and live-refresh transport (polling or
  SSE) after the review workflow is accepted by stakeholders.
