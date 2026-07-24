# Implementation Bitacora

## 2026-07-23

### UI Page Refinement

- Refined the workspace dashboard and admin Control Center with quick-access action cards, role ribbon and clearer operational metrics.
- Added a general user profile page with current application roles and workspace context.
- Added a general notification center for all authenticated users, not only administrators.
- Kept application users and Windows identities as full CRUD pages with search, status metrics and controlled role selectors.
- Verified main pages render successfully for an Application Admin session.

### UX/UI Office-Style Navigation

- Reorganized the authenticated shell into a Kaiser-branded header and Office-style command bar.
- Grouped navigation into Workspace, Operations, Administration and Governance areas based on role.
- Added a dedicated notification button with unread badge and recent-event preview.
- Kept the avatar focused on identity and sign-out while preserving backend route protection.
- Added responsive horizontal navigation behavior for smaller screens.

### Application Admin Operations

- Added a live unread notification counter to the authenticated avatar context.
- Added notification `READ`, `RESOLVED` and `EXPIRED` lifecycle operations.
- Added explicit expiration processing for delegations while retaining expired records for audit and follow-up.
- Added manual reviewer assignment from the approval queue with assignment reason and audit event.
- Connected request SLA calculation and escalation to Master Admin global SLA settings.
- Added CSV/XLSX staging with required `employee_id` validation, import batch history and quarantine resolution.

### Master Admin Control Center

- Added `MASTER_ADMIN`-only routes for administrator CRUD, global SLA/security settings and break-glass operations.
- Added a Master-only global roles and permissions matrix for the authorization policy.
- Added backend protection so the last active `MASTER_ADMIN` cannot be deactivated or lose the role.
- Added Master audit center with JSON export and append-only archive copies.
- Added audit events for application users, Windows identities, delegations and requests.
- Kept runtime SQLite as the working database; Access publication remains an explicit controlled operation.

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

### Requirements Synchronization: IAM and WFM - 2026-07-24

- Downloaded the IAM requirements tracker from commit `21d8fff` and reviewed its 61 business and technical requirements.
- Downloaded `WFM_REQ_Lifecycle_Table.xlsx` from commit `80dfb32`; it contains 32 WFM lifecycle requirements.
- Added IAM stories for rehire, blacklist, active-worker validation, contract dates, source of truth, reconciliation, ingestion preview, lineage, offboarding and dashboards.
- Added a separate WFM later-scope section to the stakeholder guide so WFM does not expand the current IAM ingestion MVP.
- Confirmed the next IAM gate is approval of official Fieldglass/Roster Lock formats, field ownership, source precedence and business validation rules.
- Updated the backlog with the new requirements follow-up work.
### Admin Control Center Closure and Ingestion Handoff - 2026-07-24

- Confirmed the Admin Control Center functional scope is complete: application users, Windows identities, Master Admin, roles, delegations, notifications, approvals, audit, session security and governance.
- Ran the full test suite successfully: 46 tests passed. The Waitress loopback test passed outside the restricted sandbox.
- Fast-forwarded `feature/admin-control-center` into `main` and published `main` to GitHub at `db1e5aa`.
- Created the next feature branch: `feature/iam-data-ingestion-foundation`.
- Defined the next objective as the IAM ingestion foundation: official Fieldglass/Roster Lock contracts, canonical worker profile, source precedence, preview, validation, duplicate detection, lineage and quarantine.
- Kept WFM requirements archived and excluded from the current IAM user-story scope and ingestion branch.

### User and Access Refinement Session - 2026-07-24

- Created `2026-07-24_USER_ACCESS_REFINEMENT.md` as the working document for today.
- Separated the Windows identity gate, IAM application account, business worker identity and local session as distinct concepts.
- Documented controlled account states, human-readable role labels, administrator boundaries, delegation continuity and notification ownership.
- Added user/access acceptance scenarios for login, authorization, last-admin protection, identity discovery, delegation expiry and session revocation.
- Explicitly kept official Fieldglass, Roster Lock and downstream template decisions out of scope until stakeholders provide the formats next week.

### User Account Lifecycle Refinement - 2026-07-24

- Added controlled application-account statuses: `ACTIVE`, `SUSPENDED`, `INACTIVE` and `PASSWORD_RESET_REQUIRED`.
- Added SQLite migration support and SQLAlchemy ORM persistence for the new status field while preserving the legacy `active` compatibility property.
- Restricted application login to accounts with `ACTIVE` status.
- Updated Application Users administration to use human-readable status selectors and status metrics.
- Added validation tests for status persistence, lifecycle transitions and invalid status rejection.
- Focused verification passed: 12 tests passed outside the restricted sandbox. Resource cleanup warnings remain non-blocking and pre-existing.

### Windows Identity Traceability Refinement - 2026-07-24

- Removed Windows identity approval and development auto-approval from the startup authorization path.
- Preflight now records the detected username and computer as an append-only `WINDOWS_IDENTITY_RECORDED` audit event.
- The preflight result carries the detected identity with no application roles; application authorization remains exclusively in the IAM account login.
- Updated launcher and login messaging to distinguish traceability from authentication.
- Retained the legacy approved-identity structures for compatibility and future policy decisions, but they are no longer a hard gate.
- Reworked the Windows identity administration view to manage traceability records only; it no longer presents roles or preflight authorization controls.

### Navigation and Command Surface Refinement - 2026-07-24

- Replaced the expanded Office-style link row with compact Bootstrap dropdown menus for Workspace, Operations, Administration and Governance.
- Added grouped links for application users, Windows traceability, notifications, delegations and Master governance.
- Reduced table density and normalized action-button sizing so audit export and archive commands stay compact and inline.
- Removed the obsolete Control Center alert for Windows identity approval and relabeled the area as traceability.
- Focused webapp, Admin Control Center and Master Admin tests passed: 8 tests passed outside the restricted sandbox.
