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

## Data Operations - Next Objective: IAM Ingestion Foundation

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
- [ ] Implement generated templates and target exports.
- [ ] Add single-writer coordination around approved changes.

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
