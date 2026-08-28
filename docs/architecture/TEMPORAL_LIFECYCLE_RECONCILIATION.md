# Temporal Lifecycle Reconciliation Review

**Date:** 2026-08-28
**Scope:** Phase 1 read-only reconciliation and audit
**Status:** Corrected in application code and covered by regression tests

## Executive finding

The historical AccessNow termination scenario was reproduced. Before the
change, `AccessNowIngestionService.apply_approved_records()` assigned the
incoming AccessNow status directly to `WorkerModel.status`. It did not compare
the source business date with dates already represented by the Worker. The
Roster Lock promotion path could create a new engagement, but it did not
recalculate the existing Worker status.

The exact two-record reproduction produced `Worker.status = TERMINATED` in
both load orders:

1. AccessNow historical termination, then Roster Lock recent presence.
2. Roster Lock recent presence, then AccessNow historical termination.

Therefore the fixture did not show two different final values when the order
was inverted. It did show the more fundamental defect: an old AccessNow
termination contaminated the single mutable Worker status regardless of the
recent Roster Lock evidence. With multiple status updates, the direct
assignment also made the final projection dependent on which source mutation
was applied last.

## Root-cause classification

| Category | Finding | Status |
|---|---|---|
| A. LAST INGESTION WINS | Direct status assignment existed for every AccessNow apply. The exact cross-source fixture was additionally affected by Roster Lock not recalculating status. | Confirmed / latent order sensitivity |
| B. CREATED_AT WINS | The Worker status path did not use `created_at_utc` to select lifecycle state. | Not the direct cause |
| C. SOURCE PRIORITY OVERRIDE | No global AccessNow-over-Roster or Roster-over-AccessNow rule was introduced. | Not observed |
| D. SINGLE STATUS MODEL | `workers.status` is one mutable analytical projection while engagements and source observations are separate rows. | Confirmed |
| E. MISSING EFFECTIVE-DATE COMPARISON | The old status assignment ignored `terminated_date`, onboarding/start dates, and equivalent business dates. | Confirmed |
| F. ENGAGEMENT COLLAPSE | The database supports multiple engagements, but the Worker status summary previously collapsed lifecycle context into one value. | Partially present |
| G. REHIRE COUPLED TO STATUS | Rehire alert generation itself did not set Worker status. | Not observed |
| H. DIRECT SOURCE-TO-PROJECTION MUTATION | AccessNow evidence was copied into the canonical status without temporal reconciliation. | Confirmed |

## Corrected model

```text
Stable analytical Worker identity
        ↓
Source observations (preserved)
        ↓
Engagement / lifecycle evidence (preserved)
        ↓
Temporal analytical status reconciliation
        ↓
Potential-rehire finding for human review
```

`Worker` remains an internal analytical identity. It is not an authoritative
HR record and its status is not a lifecycle instruction to AccessNow, Roster
Lock, Fieldglass, Salesforce, or another source system.

The corrected reconciliation:

- retains every source observation and its lineage;
- retains separate AccessNow and Roster Lock engagements;
- derives the analytical Worker status from the latest usable business date;
- does not use persistence or ingestion timestamps as a lifecycle effective
  date;
- returns `INSUFFICIENT_EVIDENCE` when an inactive AccessNow observation has no
  usable effective date;
- returns `INSUFFICIENT_EVIDENCE` when dated active and inactive observations
  conflict on the same business date;
- does not define a global source winner;
- does not use the rehire threshold to choose the Worker status.

## Timestamp semantics

For analytical status reconciliation, the implementation currently reads
business-date fields from the normalized source payload:

- AccessNow inactive: `terminated_date`, `deactivated_date`,
  `termination_date`, `end_date`, or `production_start_date`;
- AccessNow active and Roster Lock presence: `onboarding_date`,
  `worker_start_date`, `start_date`, or `hire_date`;
- other sources: `effective_date` and equivalent start-date fields.

`created_at_utc`, `updated_at_utc`, `imported_at`, file detection time, and
batch persistence time are not used to decide which lifecycle event is later.
The schema does not yet expose a dedicated normalized effective-date column,
so the current implementation extracts dates from source payload evidence.

If a source does not provide enough temporal evidence, the result must remain
reviewable rather than being inferred from ingestion order.

## Rehire detection

Rehire remains a finding/detection service. It answers whether the available
evidence falls inside the configured rehire window; it does not approve,
reject, reactivate, terminate, or otherwise decide the worker lifecycle.

The current implementation uses a 0–30 inclusive business-day comparison,
excludes configured holidays from `REHIRE_HOLIDAYS`, and falls back to source
record creation timestamps when business dates are absent. The fallback,
calendar ownership, day-boundary semantics, and date-field ownership remain
`BUSINESS DECISION REQUIRED`; they were not changed as the primary fix.

## Phase 1 safety boundary

The change only updates the local analytical projection and records history.
It does not call an authoritative downstream writer. Technical publication of
the analytical SQLite snapshot remains distinct from publication of a business
change. Any promotion, approval, merge execution, apply operation, ITSM
workflow, provisioning, or live downstream mutation must remain outside the
Phase 1 acceptance boundary or be protected by an explicit future-phase
composition/feature gate.

## Regression coverage

`tests/test_source_updates.py` now covers:

- historical AccessNow termination plus recent Roster Lock presence in both
  ingestion orders;
- preservation of both records, engagements, lineage, and Worker history;
- newer AccessNow termination over an older AccessNow active observation;
- missing effective date resulting in `INSUFFICIENT_EVIDENCE`;
- same-day active/inactive conflict resulting in
  `INSUFFICIENT_EVIDENCE`;
- selective AccessNow status apply using reconciliation instead of direct
  Worker overwrite;
- rehire detection inside and outside the configured window.

The order-independence regression compares the two complete analytical
outcomes, not just the final status.

## Remaining IAM decisions

IAM stakeholders still need to confirm the identity of each field's approved
authority, source refresh semantics, valid absence/latency windows, expected
differences, exact rehire calendar and date boundaries, finding severity, and
the evidence required to resolve a human review. Those decisions must not be
derived from whichever source file was imported last.
