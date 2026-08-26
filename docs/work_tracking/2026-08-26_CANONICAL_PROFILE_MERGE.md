# Safe Canonical Profile Merge

**Status:** In progress  
**Priority:** 2  
**Owner:** Miguel Fernandez  
**Target:** 2026-09-11  
**Estimate:** 28 hours  
**Planned branch:** `feature/canonical-profile-merge`

## Objective

Merge approved duplicate worker profiles into a surviving canonical profile while preserving historical snapshots, aliases, source lineage and audit evidence.

## Scope

- Review `worker_history_service.py`, SQLite models/repositories, employee services and `duplicate_review.html`.
- Add review and approval flow before applying a merge.
- Validate identity, conflicts and canonical-profile precedence.
- Update references safely and record a merge event.
- Provide rollback/recovery behavior and concurrency protection.

## Dependencies

- Approved canonical identifier and source-precedence matrix.
- Duplicate report and review workflow.
- Audit-event contract and retention policy.
- Backup/recovery mechanisms for the runtime SQLite copy.

## Tasks

- Define merge input, approval state and conflict outcomes.
- Implement identity and stale-version validation.
- Preserve snapshots, aliases, lineage and source identifiers.
- Update dependent references without deleting historical evidence.
- Record source, survivor, merged profile, actor, reason and correlation ID.
- Add transaction, retry, rollback and concurrent-merge safeguards.
- Document recovery and operational review steps.

## Acceptance criteria

- A merge cannot execute without authorized review/approval and a reason.
- The surviving profile and merged profile remain traceable in history.
- No required audit event, snapshot or alias is deleted.
- Conflicts and stale data stop safely with an actionable outcome.
- Retry is idempotent and rollback/recovery is documented and tested.

## Test cases

- Valid duplicate merge with complete source lineage.
- Conflicting identifiers and incomplete identity data.
- Already merged pair and repeated retry.
- Stale profile version and concurrent merge attempt.
- Failure during reference update followed by recovery.
- Historical snapshot, rehire and retention verification.

## Risks and decisions pending

- Canonical-profile precedence is the highest-impact open decision.
- Schema changes may require a versioned SQLite/Alembic migration during implementation.
- Production use requires explicit backup and recovery evidence.

## Initial database review

- The repository's local `database/snapshots/iam_runtime.sqlite` is an administrative baseline and has no `workers` table.
- The simulated runtime fixture contains 711 canonical worker rows at revision `0005_rsr_worker_details`; it predates migration `0006_worker_history`.
- Read-only analysis of that fixture found 61 normalized-name groups containing 122 canonical profiles.
- The reviewed pairs are cross-source canonical duplicates: one profile is linked to `ROSTER_LOCK` and the other to `RSR_SUPPLIER_WORKER_DETAILS`. They are not merely duplicate source rows.
- No automatic merge is authorized. The application must migrate the target runtime to `0006_worker_history`, show identifiers/source evidence, require survivor selection and a reason, and record the merge event.

## Prevention implementation

- RSR approval now revalidates strong identifiers inside the write transaction before creating a worker.
- Roster Lock promotion now uses the shared cross-source matcher before creating a worker.
- Candidate preparation revalidates all selected source records and refuses multi-canonical matches.
- Name-only matches do not silently select a canonical employee; they remain a manual-review condition.
