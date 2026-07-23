# Implementation Bitacora

## 2026-07-23

### Administrative CRUD UI Refinement

- Reworked Application Users and Windows Identities views with responsive Bootstrap layouts.
- Added status metrics, search/filter toolbars, readable tables and explicit edit actions.
- Added modal-based create and edit workflows instead of dense inline forms.
- Added mobile-friendly styling and clearer active/blocked status indicators.
- Smoke-tested both administrative routes with an authenticated Application Admin session.

### Role Catalog and Identity Discovery

- Replaced free-text role entry with controlled multi-select options and human-readable labels.
- Added `iam_identity_discovery.json` as a deduplicated pending-identity queue in the synchronized database snapshots folder.
- Added Control Center notification when pending identity discoveries exist.
- Added strict-mode behavior that records the identity and blocks access until admin approval.
- Added an approval action that promotes a pending JSON discovery into the approved identity SQLite records.

### Requests and Approval Queue

- Added ORM-backed `change_requests` and `approval_assignments` tables.
- Added request creation and requester history views.
- Added reviewer/Application Admin approval queue.
- Added approve/reject decisions with mandatory review notes.
- Blocked requesters from deciding their own requests.
- Kept publication and single-writer application as a separate downstream control.

### Module Completion: Delegation, SLA and Publication Handoff

- Added automatic queue reassignment when an approvals delegation is activated.
- Added operation-specific SLA calculation and overdue status.
- Added overdue escalation notifications when the approval queue is opened.
- Added `publication_queue` and `PublicationService` for approved requests.
- Kept backup, checksum and Access publication as the next controlled writer workflow.

### Master Governance Controls

- Added Master Admin-only governance view for audit evidence, publication and recovery.
- Added checksum-protected runtime publication with backup creation.
- Added restore from validated runtime backups with a new manifest.
- Added append-only audit events for publication and restore operations.
- Added Master Admin session revocation with enforcement at every web request.

### Windows Identity CRUD

- Added ORM-backed Windows identity repository and application service.
- Added `/admin/windows-identities` with role-aware access protection.
- Added activation, display name and identity-role management.
- Added Control Center navigation to application users and Windows identities.

### ORM and Web UI Refactor

- Added SQLAlchemy 2.x as the runtime persistence ORM.
- Added ORM models for application users, roles, approved identities, notifications and delegations.
- Converted user, notification and delegation persistence to ORM-backed repositories/services.
- Converted runtime identity and application-login reads to ORM queries.
- Kept the schema bootstrap and snapshot synchronization boundary idempotent for existing databases.
- Removed inline HTML from Flask controllers and moved views into Jinja templates.
- Added local Bootstrap 5.3.3 assets under `iam_automation/static/vendor/bootstrap/`.
- Added shared Kaiser Permanente layout, avatar menu foundation and responsive styles.
- Added the admin control center, notification view, delegation view and user administration templates.
- Added architecture notes in `docs/WEBAPP_ARCHITECTURE.md`.

### Launcher Compatibility Fix

- Restored `launch_local_webapp_process` after the webapp refactor so the PySide6 launcher continues to start Flask in a separate process.
- Preserved the loopback-only binding and clean shutdown token flow.
- Added regression coverage for the local webapp launcher.

### Verification

- Focused authentication, admin and service tests passed.
- Full test suite passed: 30 tests.
- Loopback/ephemeral-port Waitress test passed outside the restricted sandbox.

### Open Findings

- Runtime database files may change during local execution; those changes must not be reverted automatically.
- The administrative UI is a foundation. Approval reassignment, immutable audit events, publication controls and recovery remain pending.
- The current development identity auto-registration behavior remains intentionally more permissive than the future production gate.
