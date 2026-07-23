# Current Implementation Plan

**Project:** IAM Automation  
**Last updated:** 2026-07-23  
**Branch:** `feature/admin-control-center`

## Objective

Build the first maintainable local web application increment with:

- a hard SharePoint/OneDrive preflight gate;
- a local runtime SQLite working copy;
- separate Windows identity and application-account authentication;
- a responsive Flask web interface;
- SQLAlchemy ORM persistence;
- separated Jinja templates and local Bootstrap assets;
- two administrative levels: `MASTER_ADMIN` and `APPLICATION_ADMIN`.

## Deliverables

| ID | Deliverable | Status | Evidence |
|---|---|---|---|
| D01 | SharePoint path discovery and environment preflight | Completed | `startup.py`, `qt_startup.py`, preflight tests |
| D02 | Runtime SQLite synchronization and local working copy | Completed | `runtime_sync.py`, startup logs and fixtures |
| D03 | Separate Windows identity gate and application login | Completed | `identity.py`, `/login`, identity tests |
| D04 | Local Flask/Waitress launcher on loopback | Completed | `webapp.py`, `test_webapp.py` |
| D05 | Responsive web UI with Kaiser Permanente branding | Completed | `templates/`, `static/css/app.css` |
| D06 | Local Bootstrap distribution | Completed | `static/vendor/bootstrap/`, Bootstrap 5.3.3 |
| D07 | SQLAlchemy ORM persistence boundary | Completed | `infrastructure/sqlite/orm.py`, user repository and services |
| D08 | Application user CRUD and last-admin protection | Completed | `UserService`, `/admin/users`, service tests |
| D09 | Admin control center shell | Completed | `/admin`, `admin_routes.py`, role-aware avatar |
| D09.1 | Windows identity CRUD | Completed | `/admin/windows-identities`, `IdentityService` |
| D10 | Notifications and delegation workflows | Completed | Real avatar counter, read/resolve/expire states, manual reviewer assignment, SLA escalation and delegation expiry |
| D10.1 | Master session revocation | Completed | `SessionService`, `/admin/security/sessions` |
| D11 | Audit-integrated administrative operations | Completed | Master audit center, JSON export/archive and CRUD/request/delegation audit events |
| D12 | Approval queue and request lifecycle | Completed | `RequestService`, `/requests`, `/admin/approvals`, delegation reassignment and SLA escalation |
| D12.1 | Approved request publication queue | In progress | `PublicationService`, `/admin/publication`; controlled writer publication remains |
| D13 | Import, validation, quarantine and templates | In progress | CSV/XLSX staging and quarantine are available; Fieldglass mappings and downstream writes remain |
| D14 | Explicit publication, backup and restore | In progress | Master Admin governance flow, checksum, backup and restore exist; writer integration remains |
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

### Phase 4: Data operations

- Add Excel and Fieldglass ingestion.
- Validate templates and mappings before import.
- Route invalid records to quarantine.
- Add quarantine resolution and ingestion batch history.
- Generate target exports for Fieldglass and NICE IEX.

### Phase 5: Publication and validation

- Add explicit publication with backup, checksum and manifest.
- Add restore with integrity validation.
- Run integration, Windows, macOS and user acceptance tests.
- Update Smartsheet/Kanban and prepare handoff evidence.

## Definition Of Done

A work item is done when its implementation, authorization behavior, relevant tests, documentation and bitacora entry are complete. A UI-only change is not considered complete if its backend route remains unprotected.
