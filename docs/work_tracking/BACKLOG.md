# Implementation Backlog

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

Working document: [`2026-07-24_USER_ACCESS_REFINEMENT.md`](./2026-07-24_USER_ACCESS_REFINEMENT.md)

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
- [ ] Define `MASTER_ROSTER` source registration, checksum, batch and lineage contract.
- [ ] Define read-only matching preview against the canonical employee.
- [ ] Define cross-source consolidation view without canonical mutation.
- [ ] Define duplicate and repeated-identifier report columns and exports.
- [ ] Define consecutive Master Roster comparison for additions, terminations and changes.
- [ ] Define conflict view and business review filters.
- [ ] Define source adapter contract for future sources.
- [ ] Confirm duplicate rules, identifier precedence, termination and rehire semantics.
- [ ] Confirm retention, legal-hold and export-evidence requirements.
- [ ] Add explicit read-only feature gate before implementation/UAT.

### Future controlled-change items

- [ ] Promote approved Master Roster observations into canonical employees.
- [ ] Apply Master Roster enrichment and lifecycle changes.
- [ ] Confirm/merge duplicate canonical workers.
- [ ] Publish approved runtime SQLite or Access changes.
- [ ] Generate or execute downstream Data Loader submissions.

### 2026-08-26 Daily closeout — `bugfix/preflight`

- [x] Unify the desktop preflight and Waitress output into one startup log.
- [x] Format HTTP activity with method, route, status, duration and user; omit static-resource noise.
- [x] Keep **Open App** disabled until Waitress is ready and provide an explicit **Close App** action.
- [x] Disable the window close control so the application shuts down the web service cleanly.
- [x] Apply corporate desktop styling, hover states and pointer cursors to preflight actions.
- [x] Validate the preflight/webapp changes: 12 tests passed.
