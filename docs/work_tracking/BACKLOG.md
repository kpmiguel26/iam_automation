# Implementation Backlog

## High Priority

- [x] Complete the first Windows identity CRUD increment.
- [x] Replace free-text role entry with controlled human-readable selectors.
- [x] Define synchronized identity discovery JSON and pending notification.

- [ ] Complete `/admin` navigation and role-filtered avatar menu.
- [x] Add `MASTER_ADMIN`-only governance, recovery and publication routes.
- [~] Add immutable audit events for user, role, delegation, publication and restore changes; publication/restore are covered first.
- [ ] Add notification unread counter to the avatar and notification resolution routes.
- [ ] Add delegation queue reassignment without duplicating request IDs.
- [x] Add application session revocation and expiration rules.
- [~] Complete request, approval and reviewer workflow; initial CRUD is implemented, delegation and SLA remain.
- [x] Add queue reassignment and delegation integration to approval workflow.
- [x] Add initial SLA calculation and overdue escalation notification.
- [x] Enqueue approved requests as `PENDING_PUBLICATION`.

## Data Operations

- [ ] Define Excel ingestion contracts and source validation.
- [ ] Define Fieldglass ingestion adapter and mapping rules.
- [ ] Implement preview, validation and quarantine.
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
