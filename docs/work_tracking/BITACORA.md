# Implementation Bitacora

## 2026-09-04

### Documentation architecture and September milestone

- Created the documentation hub, status registry and canonical folders for bugs, features, work, pending decisions and architecture.
- Added the September 8 implementation plan for configurable Business Rules/Alerts and the published-runtime refresh alert.
- Registered BR-001–BR-006, AL-001–AL-004 and DB-001–DB-003 with explicit statuses and cross-document references.
- Recorded the current refresh-alert diagnosis: the freshness modal/polling loop exists only in `dashboard.html`, while the status endpoint is available globally.
- Preserved the Phase 1 read-only boundary; unresolved policy decisions remain pending and were not inferred from existing code.

### Refresh alert global guard

- Moved the workspace freshness modal and polling loop from the Dashboard into the shared authenticated layout so every signed-in page detects published runtime updates.
- Kept `/workspace/status` as the checksum source of truth, added an immediate initial check, and prevented duplicate modal instances.

### Legacy documentation archive

- Archived the superseded numbered POC/design series, rejected centralized architecture, July meeting materials, historical architecture presentation, WFM workbook and legacy onboarding artifact under `docs/archive/`.
- Preserved active architecture, ADRs, IAM requirements, UAT decisions, guides and current work tracking in their original active locations.
- Updated the documentation hub, archive manifest, decision log and architecture-presentation build script references.

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

- Created the historical work session [`2026-07-24_USER_ACCESS_REFINEMENT.md`](../archive/work-tracking/2026-07/2026-07-24_USER_ACCESS_REFINEMENT.md) as the working document for that day.
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

### Operational Watcher and Workspace Overview - 2026-07-24

- Added a background file watcher in the local Flask/Waitress process for pending JSON requests, configuration files and identity-discovery snapshots.
- The watcher persists file signatures in SQLite and creates one local file-backed in-app notification per new or changed file; it never imports or executes files automatically.
- Changed delegation creation from free-text usernames to active application-user selection, with backend validation and retained delegation history.
- Added SQLite-backed workspace metrics for request lifecycle, unread alerts, quarantine, publication queue, imports and active delegations.
- Added a request lifecycle bar chart and data-readiness panel to the workspace overview.
- Added regression coverage confirming a pending JSON file generates one notification only.

### Multi-Workstation Identity Discovery - 2026-07-24

- Changed identity discovery storage from one shared JSON document to independent event files under `database/snapshots/identity_discoveries/`.
- Each workstation discovery now uses a unique filename and discovery ID, avoiding concurrent overwrite and OneDrive merge conflicts.
- Preserved the legacy single-file API for existing tests and migration compatibility.
- Restricted the file watcher to the identity-discovery directory so runtime manifests are not reported as identity events.

### Safe Workspace Refresh - 2026-07-24

- Added explicit workspace version comparison using published and local SQLite checksums.
- Added a dashboard warning and `Refresh workspace` action; the application is not restarted and the user does not need to close the launcher.
- Exported the current user's local `PENDING` requests to unique shared JSON files before replacing the local SQLite snapshot.
- Added local backup, checksum validation, atomic replacement and runtime schema initialization to the refresh operation.
- Blocked refresh while local publication items are pending, preventing administrative work from being silently discarded.
- Revalidated the session roles from the refreshed SQLite when the account remains active.
- Verified workspace refresh, backup/checksum, webapp and admin regressions: 12 tests passed.

### Temporary Super Operator Bridge - 2026-07-28

- Implemented a visible, temporary `SUPER_OPERATOR` elevation for the staffing and budget transition period.
- The elevation is stored in SQLite as `temporary_elevations`; it is not persisted as a permanent application-user role and cannot be granted through the normal user CRUD.
- A `MASTER_ADMIN` grants access from the Governance menu with an application-user dropdown, ISO UTC start and expiration, and a mandatory business reason.
- Every grant, revocation and automatic expiration is recorded in the append-only audit trail. Active elevations are recalculated on login and on each authenticated request, so expiration removes operational access without requiring a code change or manual logout.
- The elevation enables operational application administration, request review, approval assignment, delegation, ingestion and quarantine workflows. It does not grant Master security, role-matrix administration, session security, audit export/archive, Access publication, Access restore or changes to the authorization model.
- Added a Master-controlled global switch to disable the bridge without rewriting security code. The control remains explicit, auditable and time-limited; no hidden backdoor or environment bypass was introduced.
- Added regression coverage for grant, revoke, expiration, invalid dates/reasons, and the existing webapp/preflight suite.
- Verification: full suite passed with 55 tests. This bridge is a temporary operating procedure and must be revoked or disabled when the permanent staffing model is approved.

### Salesforce Export and Governed Runtime Publication - 2026-07-28

- Pulled the official Salesforce Data Loader workbook from `docs/req/salesforce_template` and reviewed its 70-column structure and yellow input fields.
- Added a Salesforce export service that generates a new timestamped workbook from approved `CREATE_EMPLOYEE` and `UPDATE_EMPLOYEE` requests in local SQLite. It preserves the official template, removes sample people and records the generated artifact in audit.
- Added the Application Admin Control Center action **Salesforce export**. The output is written to the SharePoint-synchronized `generated_templates` folder; the workbook is downloaded by the operator for Salesforce/Data Loader review. No Salesforce import or automatic submission is performed.
- Enabled the governed Master Admin runtime publication path already present in the application: it validates SQLite integrity, checks the expected published checksum, creates a backup, atomically updates the SharePoint snapshot and writes its manifest.
- Added `docs/guides/SALESFORCE_EXPORT_CONFIGURATION.md` with template mapping, SharePoint folder behavior and the macOS/Windows development handoff procedure.
- Clarified the environment boundary: macOS cannot publish to real SharePoint without a local OneDrive-synchronized library. macOS development uses `tests/fixtures/sharepoint_simulated` through `IAM_SHAREPOINT_ROOT_PATH`; Windows or a Mac with OneDrive performs real SharePoint publication.

### Versioned SQLite Migrations - 2026-07-28

- Added `iam_automation/database/migrations/` and an atomic migration runner with the `schema_migrations` ledger.
- Registered the existing runtime structure as `v001_initial_schema` and added `v002_notification_indexes` as the first incremental migration.
- Runtime bootstrap now applies pending migrations idempotently after creating the current baseline schema. Future features must add a versioned migration instead of replacing `db_sharepoint` with `db_dev`.
- Added regression coverage for baseline registration, ordered application and idempotent reruns.

### Worker Identity History, Windows Merge and Daily Closure - 2026-07-31

- Integrated the Windows ingestion update from `feature/iam-data-ingestion-foundation` into `feature/worker-identity-history`.
- Implemented immutable worker profile versions, duplicate merge events and superseded-worker handling through the worker history migration.
- Preserved one canonical worker identity across source files, source identifiers, rehires and historical versions.
- Kept newly discovered and ambiguous source records in review rather than creating or enriching canonical employees automatically.
- Added source-update notifications and the Employees Updates attention indicator for operational review.
- Reset derived employee runtime data for a clean test cycle while preserving application users and roles.
- Published the feature branch and the validated `production` branch. The merge commit is `19ca5f7`.
- Full regression verification passed: **99 tests**. The loopback Waitress smoke test required local socket permission and passed when run with it.
- Deliberately excluded generated SQLite, audit, backup and request artifacts from Git; these belong to the local simulated SharePoint runtime, not the source baseline.
- Next objective is selective source reconciliation: official source contracts, vendor normalization, matching, duplicate review, employee-level decisions and operational notification cleanup.

### Canonical Profile Merge - 2026-08-26

- Created branch `feature/canonical-profile-merge` from `production`; existing uncommitted work-tracking documentation was preserved.
- Reviewed the simulated runtime database without modifying it. It contains 711 canonical workers and 61 normalized-name duplicate groups (122 profiles).
- Confirmed the reviewed duplicates are cross-source canonical profiles, typically one `ROSTER_LOCK` profile and one `RSR_SUPPLIER_WORKER_DETAILS` profile, rather than duplicate rows within one ingested file.
- Added an authenticated canonical-duplicate index and review flow with explicit survivor selection, mandatory reason, transactional merge service, audit event and superseded-worker history.
- Full regression verification passed: **141 tests**. A temporary copy of the fixture was migrated and the duplicate detector returned 61 groups / 122 profiles.
- Added the prevention barrier: RSR approval and Roster Lock promotion revalidate strong cross-source identity inside the write transaction before creating a canonical worker; name-only matches require review.
- Added regression coverage for stale `UNMATCHED` RSR approval and reverse-order Roster/RSR promotion reuse.

### Duplicate Report Closure and Change-Role Visibility Start - 2026-08-27

- Closed the duplicate-profile report engineering scope; web, CSV and XLSX output are implemented and share the same read-only report rows.
- Focused verification passed: **18 tests** in `test_worker_history.py` and `test_report_service.py`.
- Recorded stakeholder approval of duplicate rules, columns and export format as an external follow-up rather than assuming it completed.
- Created `feature/change-role-submission-visibility` from `production` and marked the work item as in progress.

### Scope Reframing — Read-only Employee & Evidence Review - 2026-08-27

- Reviewed the current architecture and confirmed that the broader codebase contains future writer capabilities, including approval, canonical updates, merge and publication.
- Defined the current release as a read-only review phase: employee, source, history, discrepancy, duplicate, request and audit evidence only.
- Deferred change-role submission visibility and all canonical employee mutation to the future controlled-change phase.
- Updated the architecture, README, operating model, webapp architecture, implementation plan, backlog and decisions to reflect the new scope.

### Master Roster Requirements Documented - 2026-08-27

- Created `2026-08-27_MASTER_ROSTER_REQUIREMENTS.md` with 15 functional and 10 non-functional requirements derived from the stakeholder-provided Touchpoint summary.
- Defined Master Roster as an independent source for read-only intake, matching preview, lineage, duplicate/conflict evidence, timeline and exports.
- Deferred canonical employee mutation, duplicate merge, approval and publication to the future controlled-change phase.
- Added requirement, dependency and future-phase items to `BACKLOG.md`; no code changes were made.

### Master Roster Read-only Staging - 2026-08-27

- Reviewed the OneDrive workbook `Kaiser_Master_Roster_2026-08-27T0610.xlsx`.
- Confirmed headers begin on row 4 and identified the two positional `LogonID` fields as NUID and NPN.
- Implemented read-only staging with independent `nuid_login_id` and `npn_login_id` fields, checksum/idempotency and required-field quarantine.
- Connected the watcher to `master_roster/*.xlsx` without creating an approval request or applying data to canonical employees.
- Real staging result: **698 staged, 0 quarantined**; canonical worker count remained **12,040**.
- Focused verification passed: **18 tests**.

### Business Rules Post-import Foundation - 2026-09-04

- Saved the business-rules architecture with a strict phase-one boundary: import first commits data to SQLite; rules evaluate afterward and only alert the human.
- Added versioned SQLite tables for `business_rules`, `business_rule_versions` and durable `rule_findings`, including severity, evidence, lifecycle status and idempotent fingerprints.
- Added an allow-listed JSON condition evaluator (`exists`, `missing`, `equals`, `not_equals`, `in`, `all`, `any`) with no Python, SQL or arbitrary expression execution.
- Connected successful watcher ingestions to post-import evaluation without allowing evaluator failures to reject or alter the import.
- Added open/critical finding counts and recent advisory findings to Overview/Dashboard; updated `docs/STATUS.md`, feature brief and implementation plan.
- Automated verification remains pending because this workstation lacks the project Python dependencies (`SQLAlchemy`, `Alembic` and `pytest`).

### Business Rules Administration CRUD - 2026-09-04

- Added the administrator Business Rules page in the Control Center.
- Users with an administrator role can create a rule draft with a field, allow-listed operator, value and severity, then activate or disable it.
- Rule status changes and creation are recorded in the existing audit trail; activation controls the post-import evaluator only.
- The interface clearly states that rules alert after SQLite persistence and never block imports in phase one.

### Business Rules Activation and Workspace Refresh Correction - 2026-09-04

- Activating a rule now evaluates all previously imported SQLite batches immediately; new manual imports use the same evaluator.
- Separated local dirty state from external refresh availability. Local rule changes now show as pending publication and do not repeatedly open the external-refresh modal.
- External refresh remains reserved for a different published runtime snapshot from SharePoint.

### Business Rules HTMX Progress Feedback - 2026-09-04

- Added HTMX partial responses for rule creation and status changes so the configured-rule region updates without a full page reload.
- Added a visible spinner and “Evaluating historical SQLite data…” indicator while activating or disabling a rule.
- Preserved the normal POST fallback for environments where HTMX is unavailable.
