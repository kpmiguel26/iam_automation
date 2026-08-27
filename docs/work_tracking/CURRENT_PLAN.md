# Current Implementation Plan

**Project:** IAM Automation  
**Last updated:** 2026-08-27
**Current phase:** Read-only Employee & Evidence Review
**Branch:** `feature/change-role-submission-visibility` (paused; no implementation planned)
**Release branch:** `production`

## Objective

Deliver a safe read-only review increment with:

- a hard SharePoint/OneDrive preflight gate;
- a local runtime SQLite working copy;
- separate Windows identity and application-account authentication;
- a responsive Flask web interface;
- SQLAlchemy ORM persistence;
- separated Jinja templates and local Bootstrap assets;
- two administrative levels: `MASTER_ADMIN` and `APPLICATION_ADMIN`.
- employee/profile, source-lineage, history, discrepancy and duplicate evidence views;
- read-only request and audit visibility;
- read-only CSV/XLSX evidence exports;
- no canonical employee mutation or database publication.

## Deliverables

| ID | Deliverable | Status | Evidence |
|---|---|---|---|
| D01 | SharePoint path discovery and environment preflight | Completed | `startup.py`, `qt_startup.py`, preflight tests |
| D02 | Runtime SQLite synchronization and local working copy | Completed | `runtime_sync.py`, startup logs and fixtures |
| D03 | Separate Windows identity gate and application login | Completed | `identity.py`, `/login`, identity tests |
| D04 | Local Flask/Waitress launcher on loopback | Completed | `webapp.py`, `test_webapp.py` |
| D05 | Responsive web UI with Kaiser Permanente branding | Completed | `templates/`, `static/css/app.css`, Office-style command bar, profile and notification center |
| D06 | Local Bootstrap distribution | Completed | `static/vendor/bootstrap/`, Bootstrap 5.3.3 |
| D07 | SQLAlchemy ORM persistence boundary | Completed | `infrastructure/sqlite/orm.py`, user repository and services |
| D08 | Application user CRUD and last-admin protection | Completed | `UserService`, `/admin/users`, service tests |
| D09 | Admin control center shell | Completed | `/admin`, `admin_routes.py`, role-aware avatar |
| D09.1 | Windows identity CRUD | Completed | `/admin/windows-identities`, `IdentityService` |
| D09.2 | User and access refinement | Completed for current development scope | [`2026-07-24_USER_ACCESS_REFINEMENT.md`](./2026-07-24_USER_ACCESS_REFINEMENT.md) |
| D10 | Notifications and delegation workflows | Completed | Real avatar counter, read/resolve/expire states, manual reviewer assignment, SLA escalation and delegation expiry |
| D10.1 | Master session revocation | Completed | `SessionService`, `/admin/security/sessions` |
| D11 | Audit-integrated administrative operations | Completed | Master audit center, JSON export/archive and CRUD/request/delegation audit events |
| D12 | Approval queue and request lifecycle | Future phase | Existing workflow code is not part of the current read-only release |
| D12.1 | Approved request publication queue | Future phase | Publication is explicitly outside current scope |
| D13 | Import, validation, quarantine and templates | In progress | Roster Lock and RSR ingestion foundations are available; selective reconciliation and official Fieldglass mappings remain |
| D13.1 | Canonical worker identity history | Completed for current increment | Alembic worker-history migration, immutable profile versions and duplicate merge events |
| D14 | Explicit publication, backup and restore | Future phase | Governance controls are retained as design/reference work |
| D15 | User acceptance, Windows validation and handoff | Pending | Cross-platform test evidence and sign-off |

## Work Sequence

### Phase 1: Foundation and access

- Maintain preflight as a hard gate before web login.
- Keep the local runtime SQLite outside the published Access database.
- Keep the control panel responsive while Flask/Waitress runs in a separate process.
- Keep development auto-registration clearly separated from future strict production authorization.

### Phase 2: Admin control center

- Complete role-aware avatar navigation.
- Complete user and Windows-identity administration.
- Add Master Admin-only settings, recovery and break-glass controls.
- Protect the last active Master Admin and Application Admin.

### Phase 3: Continuity and governance

- Complete delegations with expiration, scope and queue reassignment.
- Add in-app notifications and unread counters.
- Add immutable audit events and administrative session revocation.
- Add audit export and archive without editing original JSONL events.
- Add manual reviewer assignment and automatic SLA escalation.
- Keep expired delegations visible for administrative follow-up.

### Phase 4: User and access refinement

- Clarify Windows identity, application account, worker identity and session boundaries.
- Confirm the role and permission matrix for Master and Application Admin.
- Refine account lifecycle, identity discovery, delegation and notification rules.
- Prepare authorization and user/access acceptance scenarios.
- Keep official Fieldglass, Roster Lock and downstream template formats pending until next week.

The current objective is employee-level read-only review and evidence. Selective
reconciliation, canonical mutation, approval and publication are deferred until
the controlled-change phase is approved.

### Future Phase: Controlled changes and publication

- Add Excel and Fieldglass ingestion as controlled writer operations.
- Validate templates and mappings before import.
- Route invalid records to quarantine.
- Add quarantine resolution and ingestion batch history.
- Generate target exports for Fieldglass and NICE IEX.
- Review one source file at a time and show only new, changed, duplicate or ambiguous records.
- Preserve immutable worker versions and source lineage for every approved change.

This phase is not part of the current release.

### Current Phase: Read-only review and validation

- Verify employee directory, profiles, history, lineage, discrepancies and duplicate reports.
- Verify request/audit visibility and read-only exports.
- Confirm that browsing and reporting do not mutate canonical employee records.
- Define the feature gate or deployment separation required before enabling writer workflows.

### Future Phase: Publication and validation

- Add explicit publication with backup, checksum and manifest.
- Add restore with integrity validation.
- Run integration, Windows, macOS and user acceptance tests.
- Update Smartsheet/Kanban and prepare handoff evidence.

## End-of-Day Position - 2026-08-27

- Feature and release branches are published.
- Full regression suite is green at 99 tests.
- Runtime fixture changes are intentionally local and excluded from Git.
- IAM is currently in the read-only review phase. Change-role submission implementation is deferred; pending work is tracked in `BACKLOG.md`.

## Definition Of Done

A work item is done when its implementation, authorization behavior, relevant tests, documentation and bitacora entry are complete. A UI-only change is not considered complete if its backend route remains unprotected.
