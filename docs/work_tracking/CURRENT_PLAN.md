# Current Implementation Plan

**Project:** IAM Automation  
**Last updated:** 2026-07-24  
**Branch:** `feature/iam-data-ingestion-foundation`

## Objective

Build the first controlled data-ingestion increment on top of the completed local web application and Admin Control Center:

- confirm the official Fieldglass and Roster Lock source contracts;
- define a canonical worker profile and source precedence;
- ingest approved Excel/CSV sources into SQLite through ORM services;
- preview additions, updates, duplicates and conflicts before publication;
- route invalid or disputed records to quarantine;
- preserve the single-writer, audit, backup and checksum boundaries.

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
| D09 | Admin control center shell | Completed | `/admin`, `admin_routes.py`, role-aware avatar; merged to `main` |
| D09.1 | Windows identity CRUD | Completed | `/admin/windows-identities`, `IdentityService` |
| D10 | Notifications and delegation workflows | Completed | Real avatar counter, read/resolve/expire states, manual reviewer assignment, SLA escalation and delegation expiry |
| D10.1 | Master session revocation | Completed | `SessionService`, `/admin/security/sessions` |
| D11 | Audit-integrated administrative operations | Completed | Master audit center, JSON export/archive and CRUD/request/delegation audit events |
| D12 | Approval queue and request lifecycle | Completed | `RequestService`, `/requests`, `/admin/approvals`, delegation reassignment and SLA escalation |
| D12.1 | Approved request publication queue | In progress | `PublicationService`, `/admin/publication`; controlled writer publication remains |
| D13 | Import, validation, quarantine and templates | In progress | CSV/XLSX staging and quarantine are available; Fieldglass mappings and downstream writes remain |
| D14 | Explicit publication, backup and restore | In progress | Master Admin governance flow, checksum, backup and restore exist; writer integration remains |
| D15 | User acceptance, Windows validation and handoff | Pending | Cross-platform test evidence and sign-off |
| D16 | IAM data ingestion foundation | Next | Fieldglass/Roster Lock contract, worker model, preview, validation and quarantine |

## Work Sequence

### Phase 1: Foundation and access

- Maintain preflight as a hard gate before web login.
- Keep the local runtime SQLite outside the published Access database.
- Keep the control panel responsive while Flask/Waitress runs in a separate process.
- Keep development auto-registration clearly separated from future strict production authorization.

### Phase 2: Admin control center - completed

- Complete role-aware avatar navigation.
- Complete user and Windows-identity administration.
- Add Master Admin-only settings, recovery and break-glass controls.
- Protect the last active Master Admin and Application Admin.

The Admin Control Center was merged to `main` on 2026-07-24. Remaining admin-related work is release hardening, not a blocker for starting ingestion.

### Phase 3: Continuity and governance

- Complete delegations with expiration, scope and queue reassignment.
- Add in-app notifications and unread counters.
- Add immutable audit events and administrative session revocation.
- Add audit export and archive without editing original JSONL events.
- Add manual reviewer assignment and automatic SLA escalation.
- Keep expired delegations visible for administrative follow-up.

### Phase 4: Data operations - current objective

1. Confirm the official Fieldglass report and Roster Lock template.
2. Define the canonical worker identifier and field-level source precedence.
3. Extend the SQLite ORM with worker profile, source lineage and discrepancy records.
4. Implement Fieldglass and Roster Lock adapters behind a shared ingestion contract.
5. Add preview, duplicate detection, date validation and business-rule hooks.
6. Route invalid, conflicting or incomplete records to quarantine.
7. Keep publication and downstream exports behind explicit approval and checksum controls.

### Phase 5: Publication and validation

- Add explicit publication with backup, checksum and manifest.
- Add restore with integrity validation.
- Run integration, Windows, macOS and user acceptance tests.
- Update Smartsheet/Kanban and prepare handoff evidence.

## Next Branch Goal

`feature/iam-data-ingestion-foundation` is the active feature branch. It should contain only the IAM ingestion foundation. WFM requirements remain archived for future production planning and are not part of this branch.

The branch is complete when one approved Fieldglass sample and one approved Roster Lock sample can be loaded into local SQLite, previewed, validated, quarantined when necessary, and verified through integration tests without modifying the published Access database.

## Definition Of Done

A work item is done when its implementation, authorization behavior, relevant tests, documentation and bitacora entry are complete. A UI-only change is not considered complete if its backend route remains unprotected.
