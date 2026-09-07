# SQLite consumer transition — September 7, 2026

Status: Active. Branch: `fix/skip-unchanged-employee-updates`.

## Confirmed state

The September 4 baseline (`bbead33`) writes source facts for AccessNow,
Roster Lock, Master Roster and RSR, then clears valid staged-row JSON in a
second transaction. Worker versions write relational field history. Several
consumers still expect the removed JSON; the transition is not complete.

A read-only inspection of the repository-root `runtime.sqlite` found revision
`0007_source_observations`, 8 import batches, 24,998 ingestion records with
non-empty normalized JSON and 12,867 worker versions. Source facts, relational
worker history and compact employee tables were absent. This is evidence about
that file only; the launcher's configured runtime has not been identified.
No application was started and no runtime migration or reset was performed.

## Fixed in this increment

- Business rules reconstruct input from `fact_source_snapshot`, `dim_field`
  and `fact_worker_field`, using the existing legacy/quarantine fallback.
  Payloads are loaded once per applicable record per evaluation. Existing
  finding JSON remains an audit snapshot; this change does not migrate it.
- Rules match populated fields after JSON cleanup and no longer falsely
  flag those fields as missing. Relational evidence takes precedence over stale
  JSON, and reruns do not duplicate findings.
- Source update preview uses the same relational reader instead of attempting
  `json.loads("")` after a fresh import.
- A simulated evaluation failure rolls back findings, preserves the committed
  import and facts, and allows a successful retry.
- Master Roster reimports now compare canonical non-empty values against the
  latest relational source facts, so an unchanged matched row records only its
  observation and creates no duplicate engagement, lineage rows or worker
  version. Real changes write relational history with a compact changed-field
  list and timestamp.
- The import result and review card distinguish matched rows, material employee
  changes and rows with no material changes. Valid source rows keep their
  relational facts while legacy payload JSON remains empty; quarantine payloads
  are retained for review.

## Verification

- `tests/test_business_rule_service.py`: 6 passed, including four new
  relational/transactional regressions and two existing legacy tests.
- Rules plus `tests/test_employee_domain.py`: 11 passed.
- Initial full suite: 176 passed, 9 failed, 1 skipped. All nine failures were
  reproduced with the baseline rule implementation in the four failing test
  modules (24 passed, 9 failed); no workspace source replacement was needed.
- Final full suite after the no-change transition: **181 passed, 5 failed,
  1 skipped** (8.01 seconds). The five remaining watcher failures existed on
  the baseline. `git diff --check` passed. Remaining failures and reader work are
  tracked in `../work_tracking/BACKLOG.md`.

## Remaining migration work

1. Validate the no-change decision across AccessNow, Roster Lock, Master Roster
   and RSR adapters with representative production-shaped files.
2. Migrate the remaining employee, report, rehire, compact projection and
   history readers. `version_dict` currently returns an empty snapshot for new
   relational versions; writing history is not equivalent to displaying it.
3. Update remaining tests that explicitly require source/version JSON, keeping
   checks for actual identifiers and historical values in relational tables.
4. Reconcile five watcher test failures with current notification and manual
   ingestion behavior; those failures also occur on the baseline.
5. Identify the runtime actually used by the launcher, validate migrations on
   a disposable copy, and verify rollback/counts/lineage before any data cleanup.
6. Finish controlled retention and cleanup. The design still differs from the
   code: legacy tables are created, imports temporarily persist JSON, and
   valid-row cleanup occurs in a separate transaction. Do not describe this
   as a completed JSON-free or atomic end-to-end import migration.
