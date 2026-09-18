# Implementation Backlog

## 2026-09-18 Presentation meeting — Quarantine and rules follow-up

Source: [`quarantine rules meeting notes`](../quarantine-rules/meeting%209-18-2026.md).

The team confirmed that Phase One is a functional MVP with a read-only IAM
automation boundary. Findings remain advisory evidence for human review; no
authoritative employee changes, approvals or blocking imports are introduced.

### Decisions and operating agreements

- [ ] Limit termination history retained in the standardized dataset to the
  last three years, preserving repeat-hire context and documenting the
  retention rule.
- [ ] Replace recurring demos with weekly written updates and a one-hour
  Monday working session.
- [ ] Standardize user-facing timestamps on Pacific Time where applicable and
  always display the timezone explicitly, including UTC when used.
- [ ] Confirm Access Now regulatory closure dates and incorporate them into the
  active operating-calendar configuration.
- [x] Require an explicitly selected and pinned calendar/context version for
  rule evaluation; do not infer timezone, operating weekdays or holidays from
  UTC, host settings or environment variables.
- [x] Show an actionable configuration message when the calendar is missing or
  invalid while preserving the non-blocking Phase One import boundary.
- [x] Treat operating weekdays, date-boundary convention and interval inclusion
  as versioned business decisions loaded from the configured calendar/context;
  changing them requires a new configuration version, not code changes.
- [x] Retire the legacy `RehireAlertService` path from runtime. Rehire logic,
  notifications and archive actions must come from user-created Business Rules;
  retain the old service only as historical documentation.

### Implementation backlog from the meeting

- [ ] Continue Phase Three factorization of the rules engine into separate
  services, configuration, execution, query and related modules; preserve the
  current operators and business-days-between calculation.
- [ ] Publish an external SOP for the Excel-like semantic rule language and
  provide user training; training is currently blocked until the rule language
  is learned and stabilized.
- [ ] Complete the editable Excel-like rule configuration/wizard, including
  multiple comparisons, user-defined calculated values and database-backed
  rule definitions.
- [ ] Fix data export so separate fields remain separate, including the email
  values currently merged during export.
- [ ] Verify the agnostic ingestion flow for report mapping, normalized data,
  identity matching, canonical analytical identity and cross-source
  reconciliation.
- [x] Remove source-file readers and normalizers from Rules Engine execution;
  `BEFORE` consumes staged database evidence by `batch_id`.
- [x] Introduce a source-neutral `EvidenceRepository` and reconstruct rule
  payloads from generic ingestion/star-schema tables.
- [x] Move rule source and field choices to the DB-backed catalog
  (`dim_source`, `dim_field`, `source_field_mapping`) with migration `0022`.
- [x] Close metadata and adapter-result escape hatches at the engine boundary;
  use typed metadata and explicit mapping/source identifiers.
- [x] Persist new rule scopes and field operands with stable
  `source_id`/`field_id` values while retaining a compatibility fallback for
  historical versions.
- [ ] Backfill historical rule versions to stable catalog IDs after confirming
  the retained legacy keys are no longer needed for external consumers.
- [ ] Split ingestion into an explicit generic `stage → BEFORE → promote`
  lifecycle; current adapters still own completion markers and source-fact
  writes in their own transactions.

### Follow-up ownership

- [ ] Miguel — send a weekly written summary covering agnostic architecture and
  rules-documentation progress.
- [ ] Miguel — provide rule-language training after the SOP/rule language is
  ready.
- [ ] Sofia — send the meeting follow-up email later today.

## 2026-09-10 Phase 1 review closure and next work session

Management and leadership reviewed the current increment and approved
continuing the polish of **Phase 1 — Read-only Employee & Evidence Review**.
The approval does not expand the scope into authoritative writes, approval,
blocking imports or automated rehire decisions.

### Completed today

- [x] Confirmed the generic rule engine can create reusable rules with explicit
  left operand, operator and right operand conditions; no rehire template or
  hard-coded business rule was introduced.
- [x] Added and verified composite-rule recipes for the 30-day rehire scenario
  and cross-source Roster Lock/Master Roster comparisons.
- [x] Kept report-field choices scoped to the selected report in the guided
  builder and fixed the explicit-condition validation path so valid compound
  rules can continue.
- [x] Refined Business Rules presentation with a guided builder, rule registry
  cards and responsive layouts while preserving server-rendered Flask/Jinja
  and HTMX interactions.
- [x] Refined Quarantine to show one card per configured rule, including rules
  with zero findings; clicking a card opens a rule-detail page with the
  affected-record table.
- [x] Added HTMX rule filtering in Quarantine. The filter button shows a
  yellow updating state with a loader while results refresh without a full
  page reload.
- [x] Saved and verified the operating calendar, weekdays, holidays, context
  versions and date-boundary settings in the local SQLite evidence store.
- [x] Focused regression suite passed: 28 tests.

### Backlog for tomorrow

- [ ] Pin the exact calendar version in each rule context/version. The current
  context stores the calendar ID, while the evaluator still resolves the
  calendar's current version; add an additive migration and regression tests so
  historical findings remain reproducible.
- [ ] Create the generic 30-day rehire rule through the UI after all required
  sources are ingested; keep it `DRAFT`, run the preview, then review the
  finding evidence before activation.
- [ ] Execute boundary fixtures for 0, 1, 29, 30 and 31 business days,
  including a configured holiday and missing-date cases.
- [ ] Verify the 30-day rule's source matching, worker lineage, batch lineage,
  context version, calendar version and evidence in Quarantine.
- [ ] Add regression coverage for Quarantine's rule cards, zero-finding rules,
  HTMX rule-select filtering and the rule-detail table response.
- [ ] Improve composite finding presentation so all operands, sources and
  calculated values are visible without requiring raw JSON inspection.
- [ ] Run the complete test suite and record the result before the next
  management/UAT checkpoint.

### Phase 1 guardrail

Rules remain advisory and non-blocking. Rehire detection produces local
findings and evidence only; it must not approve, reject, merge, correct or
publish employee data to an authoritative source.

## 2026-09-07 SQLite consumer transition

Evidence: [transition review](../bugs/2026-09-sqlite-consumer-transition.md).

The ingestion adapter structure is documented in
[`../architecture/INGESTION_ARCHITECTURE.md`](../architecture/INGESTION_ARCHITECTURE.md).

- [x] Split common ingestion helpers and result compatibility contracts.
- [x] Split Master Roster, Roster Lock, RSR and AccessNow format components.
- [x] Centralize source adapter dispatch and move star-fact persistence to SQLite infrastructure.
- [x] Define source-separated write model, employee identity keys and AccessNow status ownership.
- [ ] Add source-specific employee write tables and migrations.
- [ ] Add current-year AccessNow termination filter and status-only writer.

- [x] Read relational facts in business rules and source update preview.
- [x] Verify rule idempotency, evidence and rollback independently of imports.
- [x] Fix row deduplication after JSON cleanup (Master Roster regression).
- [ ] Migrate remaining report, employee, rehire, compact projection and history readers.
- [x] Replace outdated JSON assertions with relational content checks.
- [ ] Reconcile five existing watcher test failures with current behavior.
- [ ] Identify the active runtime and validate migration on a disposable copy.
- [ ] Finish atomic cleanup and controlled retention; legacy JSON removal is incomplete.

## 2026-09-04 active milestone

Canonical plan: [`../work/2026-09-04-implementation-plan.md`](../work/2026-09-04-implementation-plan.md). Status registry: [`../STATUS.md`](../STATUS.md).

- [ ] DB-001/DB-002 — move refresh freshness polling to the authenticated shared layout; see [`../bugs/2026-09-refresh-alert.md`](../bugs/2026-09-refresh-alert.md).
- [ ] BR-001–BR-006 — implement configurable Business Rules; see [`../features/2026-09-business-rules-framework.md`](../features/2026-09-business-rules-framework.md).
- [ ] AL-001–AL-004 — implement configurable Alert Definitions and dashboard; see [`../features/2026-09-business-rules-framework.md`](../features/2026-09-business-rules-framework.md).
- [ ] Resolve P-001–P-007 before treating policy behavior as complete; see [`../pending/2026-09-business-rules-decisions.md`](../pending/2026-09-business-rules-decisions.md).

Older sections below retain historical work items and prior phase detail. For
current status, use [`../STATUS.md`](../STATUS.md); do not infer completion
from an older unchecked item without checking the linked evidence.

## High Priority

- [x] Complete the first Windows identity CRUD increment.
- [x] Replace free-text role entry with controlled human-readable selectors.
- [x] Define synchronized identity discovery JSON and pending notification.

- [x] Complete `/admin` navigation and role-filtered avatar menu.
- [x] Add Master Admin CRUD, global settings and mandatory-reason break-glass flow.
- [x] Add Master-only global roles and permissions matrix.
- [x] Protect the last active MASTER_ADMIN in backend role/deactivation changes.
- [x] Add `MASTER_ADMIN`-only governance, recovery and publication routes.
- [x] Add immutable audit events for users, identities, delegations, requests, publication and restore changes.
- [x] Add Master audit JSON export and append-only archive operation.
- [x] Add notification unread counter to the avatar and notification resolution routes.
- [x] Add notification read, resolved and expired states.
- [x] Share notification events through one JSON per event with per-user read markers and an immutable recipient snapshot.
- [x] Add delegation queue reassignment without duplicating request IDs.
- [x] Add manual reviewer assignment and SLA escalation.
- [x] Add expired delegation administration.
- [x] Rework authenticated navigation into Office-style command bar with notification preview.
- [x] Add general user profile and notification pages for non-admin users.
- [x] Add application session revocation and expiration rules.
- [~] Complete request, approval and reviewer workflow; initial CRUD is implemented, delegation and SLA remain.
- [x] Add queue reassignment and delegation integration to approval workflow.
- [x] Add initial SLA calculation and overdue escalation notification.
- [x] Enqueue approved requests as `PENDING_PUBLICATION`.

## User And Access Refinement - Current Work Session

Historical working document: [`2026-07-24_USER_ACCESS_REFINEMENT.md`](../archive/work-tracking/2026-07/2026-07-24_USER_ACCESS_REFINEMENT.md)

- [ ] Approve the identity-layer glossary: Windows identity, application account, worker identity and session.
- [~] Confirm controlled account states and recovery behavior; initial SQLite/ORM implementation is complete, recovery and rehire policy remain open.
- [ ] Approve the human-readable role and permission matrix.
- [ ] Confirm last-administrator protection and self-demotion rules.
- [ ] Confirm identity discovery, pending approval and development strict-mode behavior.
- [ ] Confirm reviewer assignment, delegation scope, expiry and fallback escalation.
- [ ] Confirm notification recipients, severity, lifecycle and retention.
- [ ] Execute the user/access UAT checklist and record stakeholder sign-off.
- [ ] Carry the approved decisions into the ORM, services, routes and authorization tests.

## Data Operations - Completed Foundation / Next Objective: Selective Source Reconciliation

- [x] Define initial CSV/XLSX ingestion contract and source validation.
- [ ] Confirm official Fieldglass report and mapping owner.
- [ ] Confirm official Roster Lock template and submission rules.
- [ ] Define canonical worker identifier and source precedence matrix.
- [ ] Define worker profile, source lineage and discrepancy ORM entities.
- [ ] Define Fieldglass ingestion adapter and mapping rules.
- [ ] Define Roster Lock ingestion adapter and mapping rules.
- [ ] Add ingestion preview for additions, updates, duplicates and conflicts.
- [ ] Add business validation hooks for rehire, blacklist, active worker and contract dates.
- [x] Implement initial validation and quarantine workflow.
- [x] Add quarantine resolution and import batch history.
- [x] Add Roster Lock and RSR Supplier Worker Details ingestion foundations.
- [x] Add canonical worker history, immutable profile versions and duplicate merge events.
- [x] Keep source-file approval review-only until an explicit worker decision is made.
- [x] Add source-update notifications and an Employees Updates attention indicator.
- [ ] Implement generated templates and target exports.
- [ ] Add single-writer coordination around approved changes.
- [ ] Refine selective employee-level source review and application outcomes.
- [ ] Add duplicate clusters, merge recommendations and unresolved-discrepancy reporting.
- [ ] Confirm vendor normalization and source precedence with stakeholders.

## Publication And Recovery

- [ ] Add pending-publication state.
- [x] Create backup before every publication.
- [x] Generate checksum and manifest for runtime snapshots.
- [x] Add Master Admin restore flow with current-state backup.
- [ ] Add conflict detection between local and published SQLite snapshots.

## Testing

- [ ] Add ORM repository tests for all new aggregates.
- [ ] Add authorization matrix tests for Master and Application Admin.
- [ ] Add notification expiry and delegation expiry tests.
- [ ] Add import/quarantine integration tests.
- [ ] Add publication/restore checksum tests.
- [ ] Validate the Windows launcher with Python 3.10.
- [ ] Validate macOS launcher with Python 3.10+.
- [ ] Run user acceptance scenarios and record sign-off.
- [x] Run the full regression suite after the Windows ingestion merge: 99 tests passed.

## Documentation And Delivery

- [ ] Update administrator guide with the new control center.
- [ ] Update recovery guide with runtime SQLite publication and restore.
- [ ] Keep Smartsheet CSV synchronized with this backlog.
- [ ] Prepare a feature pull request from `feature/admin-control-center`.
- [ ] Merge only after tests and review are complete.

## Requirements Follow-up

- [x] Download the IAM Software Requirements Tracker from the Windows push.
- [x] Add IAM business validation and reconciliation user stories to the stakeholder guide.
- [x] Download and archive the WFM lifecycle requirements workbook.
- [x] Archive the WFM lifecycle workbook separately for future production planning; exclude it from current IAM user stories.
- [ ] Confirm official Fieldglass and Roster Lock formats with stakeholders.
- [ ] Define canonical worker identifier, source precedence and data lineage.
- [ ] Implement rehire, blacklist, active-worker and contract-date validation rules.
- [ ] Implement Roster Lock/Fieldglass reconciliation and discrepancy workflow.
- [x] Add worker version history and duplicate-worker merge evidence.
- [ ] Confirm selective source-update review behavior with stakeholders.

## September 2026 IAM Action Items

Source: [`2026-08-25_MIGUEL_FERNANDEZ_ACTION_ITEMS_ESTIMATE.md`](../2026-08-25_MIGUEL_FERNANDEZ_ACTION_ITEMS_ESTIMATE.md)

Booking baseline: **75 hours of planned work + 5 hours contingency = 80 hours recommended**. The source estimate contains a reconciliation note: its contingency row says 8 hours while the executive summary says 5, and the second date window is listed as 42 hours although its detailed tasks total 47 hours. Until stakeholders confirm otherwise, this backlog uses the executive 80-hour booking recommendation.

All items start in `Backlog` and require a dedicated `feature/<name>` branch before implementation.

### Priority 1 — target 2026-09-04

- [ ] **Finalize audit events** — 8 h, Miguel; see [`2026-08-26_AUDIT_EVENTS_FINALIZATION.md`](./2026-08-26_AUDIT_EVENTS_FINALIZATION.md).
- [ ] **Add change-role submission visibility** — 10 h, Miguel; see [`2026-08-26_CHANGE_ROLE_SUBMISSIONS_VISIBILITY.md`](./2026-08-26_CHANGE_ROLE_SUBMISSIONS_VISIBILITY.md). Deferred to the future controlled-change phase; branch exists but implementation is paused.
- [x] **Create duplicate-profile export report** — 12 h, Miguel; see [`2026-08-26_DUPLICATE_REPORT.md`](./2026-08-26_DUPLICATE_REPORT.md). Engineering scope complete and verified; stakeholder validation remains an external follow-up.
- [ ] **Validate Salesforce/Data Loader export and application regression** — 6 h Salesforce validation, part of the 14 h combined testing allocation; see [`2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md`](./2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md).

### Priority 2 — target 2026-09-11

- [~] **Implement safe canonical-profile merge and duplicate-prevention matching** — 28 h, Miguel; see [`2026-08-26_CANONICAL_PROFILE_MERGE.md`](./2026-08-26_CANONICAL_PROFILE_MERGE.md).
- [ ] **Complete history, retention and regression validation** — 8 h, combined with the 6 h Salesforce validation above for 14 h total testing; see [`2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md`](./2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md).
- [ ] **Prepare SOP and technical handoff** — 3 h; see [`2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md`](./2026-08-26_VALIDATION_SALESFORCE_RETENTION_HANDOFF.md).

### Dependencies and operational support

- [ ] Salesforce Team confirms the final workbook/template, administrative access and Data Loader process.
- [ ] Sofia Moya confirms the five-day inactivity report availability and format.
- [ ] Stakeholders approve duplicate rules, canonical-profile precedence, retention policy and recovery behavior.
- [ ] Sophie Moya Bermudez receives duplicate-roster evidence for the biweekly meeting when requested.
- [ ] Amanda Madrigal owns the Report Studio roster-lock consolidation test; IAM provides data and defect support if the canonical model is affected.
- [ ] Vendor communication/access remains delayed as an operational control until the flow is stable.

### Current phase boundary — Read-only Employee & Evidence Review

- [x] Confirm that canonical employee mutation is outside the current release scope.
- [x] Defer change-role submission creation, approval and application to a future phase.
- [ ] Add an explicit feature gate or read-only deployment profile before production use.
- [ ] Confirm read-only UAT scenarios and evidence-export permissions.

## Master Roster Requirements — 2026-08-27

Working document: [`2026-08-27_MASTER_ROSTER_REQUIREMENTS.md`](./2026-08-27_MASTER_ROSTER_REQUIREMENTS.md)

### Requirements and read-only design

- [ ] Confirm official Master Roster folder, file name, owner and delivery cadence.
- [ ] Confirm Master Roster workbook sheets, headers, required fields and row boundaries.
- [x] Define and implement `MASTER_ROSTER` source registration, checksum, batch and lineage staging contract.
- [x] Connect the watcher to `master_roster/*.xlsx` without creating an approval/apply workflow.
- [x] Capture NUID and NPN login IDs as separate fields when the workbook repeats `LogonID`.
- [x] Add sequential manual import from staged source files into employee history.
- [x] Create a canonical employee when a reliable imported row has no existing history.
- [x] Add local HTMX timeline, import status badges and request loading indicators.
- [ ] Define read-only matching preview against the canonical employee.
- [ ] Define cross-source consolidation view without canonical mutation.
- [ ] Define duplicate and repeated-identifier report columns and exports.
- [ ] Define consecutive Master Roster comparison for additions, terminations and changes.
- [ ] Define conflict view and business review filters.
- [ ] Define source adapter contract for future sources.
- [ ] Confirm duplicate rules, identifier precedence, termination and rehire semantics.
- [ ] Confirm retention, legal-hold and export-evidence requirements.
- [ ] Add explicit feature-state gate for duplicate resolution and publication before UAT.

### Future controlled-change items

- [ ] Apply source-specific enrichment and lifecycle changes after historical import.
- [ ] Confirm/merge duplicate canonical workers.
- [ ] Publish approved runtime SQLite or Access changes.
- [ ] Generate or execute downstream Data Loader submissions.

### 2026-08-27 DataTable standardization

- [x] Apply local DataTables controls to flat application tables: pagination,
  all-loaded-row view, sorting, search, Copy, CSV and Excel export.
- [x] Preserve server-side pagination for large employee/source datasets and
  provide explicit load-all behavior before client-side export.
- [x] Document table coverage and the expandable-detail exception in
  [`2026-08-27_DATATABLE_COVERAGE.md`](./2026-08-27_DATATABLE_COVERAGE.md).

### 2026-08-26 Daily closeout — `bugfix/preflight`

- [x] Unify the desktop preflight and Waitress output into one startup log.
- [x] Format HTTP activity with method, route, status, duration and user; omit static-resource noise.
- [x] Keep **Open App** disabled until Waitress is ready and provide an explicit **Close App** action.
- [x] Disable the window close control so the application shuts down the web service cleanly.
- [x] Apply corporate desktop styling, hover states and pointer cursors to preflight actions.
- [x] Validate the preflight/webapp changes: 12 tests passed.
