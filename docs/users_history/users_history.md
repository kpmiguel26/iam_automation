# IAM Automation User Stories and Stakeholder Guide

**Document status:** Working stakeholder draft  
**Product:** IAM Automation  
**Branch:** `feature/admin-control-center`  
**Audience:** Business stakeholders, Product Management, Operations, QA and Engineering

## 1. Purpose

IAM Automation is a local-first application for managing workforce identity requests, approvals, operational data and controlled publication. The application uses a local runtime SQLite database for day-to-day work and keeps the published Access database as a controlled secondary source and recovery target.

The application is intentionally separated into two startup and access gates:

1. The desktop preflight verifies the local SharePoint/OneDrive workspace, Access database, published SQLite snapshot, folders and current workstation identity.
2. The web application login validates the application account and creates the local session.

No user reaches the application dashboard before the environment gate succeeds.

## 2. Personas and Roles

| Persona | Main responsibility | Access level |
|---|---|---|
| Requester | Submit and track identity requests | Request intake and own request history |
| Reviewer | Review assigned requests and record approval decisions | Approval queue |
| Writer | Operate controlled downstream publication activities | Publication-related operations |
| Auditor | Review evidence and audit history | Read-only audit access |
| Application Administrator | Run daily operations, users, identities, approvals, imports and continuity workflows | Operational administration |
| Master Administrator | Control administrators, security, global rules, recovery and break-glass actions | Full governance administration |

`ADMINISTRATOR` remains a compatibility alias for `APPLICATION_ADMIN`. Human-readable labels are used in forms while the application stores stable role codes.

## 3. User Stories

### 3.1 Startup and Access

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-001 | As a user, I want the application to find my synchronized SharePoint folder before login so that I work against the correct workspace. | The preflight resolves a local path, never treats a web URL as a database path, and shows the resolved route. | Complete |
| US-002 | As a user, I want to browse for the workspace when automatic discovery fails so that I can recover without editing configuration files. | Browse and Retry are available; invalid paths explain the missing resource. | Complete |
| US-003 | As a user, I want the published SQLite snapshot copied to my local runtime location so that my work is isolated from the synchronized file. | The snapshot is validated, copied locally, and recorded with checksum information. | Complete |
| US-004 | As a user, I want my workstation identity checked separately from my application account so that the machine gate and web login remain distinct. | The Windows/macOS identity is detected during preflight; the application account is requested only at `/login`. | Complete |
| US-005 | As an administrator, I want the control panel to remain available while the local webapp runs so that I can open, monitor and stop the application safely. | PySide6 control panel, loopback webapp, browser launch and Stop Web App are available. | Complete |

### 3.2 Application Login and Session

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-006 | As a user, I want to sign in with my IAM Automation account after preflight so that my application permissions are enforced. | The account is validated against local SQLite; passwords are never stored in plaintext. | Complete |
| US-007 | As a user, I want a visible profile menu so that I can see my username, roles, workspace and session status. | Avatar menu links to My Profile, Notifications and Sign out. | Complete |
| US-008 | As a Master Administrator, I want active sessions to be revocable so that access can be removed during an incident or role change. | Revocation is recorded and the next request clears the session. | Complete |

### 3.3 Request and Approval Operations

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-009 | As a Requester, I want to create an identity request using controlled fields so that incomplete or ambiguous submissions are reduced. | Request type is selected from a controlled list and the request receives a stable ID. | Complete |
| US-010 | As a Requester, I want to see my request status and history so that I know whether action is required. | The request list shows lifecycle state, timestamps and reviewer information. | Complete |
| US-011 | As a Reviewer, I want to see a queue of pending requests so that I can approve or reject work assigned to me. | Queue actions require an authenticated reviewer or administrator and record a decision note. | Complete |
| US-012 | As an Application Administrator, I want to assign a reviewer manually so that the queue has clear ownership. | Assignment keeps the original request ID and records the assignment event. | Complete |
| US-013 | As an administrator, I want overdue requests escalated according to SLA so that absence does not silently block operations. | SLA settings are evaluated and overdue notifications are generated. | Complete |
| US-014 | As an administrator, I want approved requests placed in a publication queue so that database changes are not written directly from the web route. | Approved requests enter `PENDING_PUBLICATION`; controlled writer publication remains explicit. | In progress |

### 3.4 User and Identity Administration

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-015 | As an Application Administrator, I want to create and update application users so that access can be managed without editing SQLite manually. | Form validates username, display name, password and role selections; changes are audited. | Complete |
| US-016 | As a Master Administrator, I want to create and maintain administrators so that operational and security responsibilities remain separate. | Only Master Admin can assign or remove `MASTER_ADMIN`; the last active administrator is protected. | Complete |
| US-017 | As an administrator, I want to register approved Windows identities so that workstation identity and application account remain separate records. | Identity records support status, roles and audit history. | Complete |
| US-018 | As an administrator, I want newly discovered identities to appear as pending work so that identity registration is reviewable. | The synchronized discovery JSON is read at startup and surfaced as a notification/action in the control center. | Complete |

### 3.5 Continuity and Delegation

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-019 | As an administrator, I want to assign a temporary delegate when an approver is absent so that work continues during leave or illness. | Delegation has principal, delegate, scope, start, expiration and reason. | Complete |
| US-020 | As a delegate, I want to see the scope and expiration of my temporary access so that I do not operate beyond the approved period. | The delegation is time-bound and cannot be transferred by the delegate. | Complete |
| US-021 | As an administrator, I want pending requests reassigned without duplication so that continuity does not change the request history. | Reassignment preserves request ID and records the queue event. | Complete |
| US-022 | As an administrator, I want expired delegations processed and visible so that follow-up actions are not hidden. | Expiration can be processed from the Delegations page and remains auditable. | Complete |

### 3.6 Notifications

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-023 | As a user, I want a notification indicator in the avatar so that I can see pending action without leaving my current page. | The avatar shows the real unread count from SQLite. | Complete |
| US-024 | As an administrator, I want to mark, resolve and review notifications so that operational work has a clear end state. | Notifications support unread, read, resolved and expired states. | Complete |
| US-025 | As an administrator, I want alerts for identity discovery, SLA escalation, quarantine, conflicts and publication errors so that exceptions are visible in-app. | Notifications link to the affected route or object where available. | Complete / expanding |

### 3.7 Import, Quarantine and Data Operations

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-026 | As an Application Administrator, I want to upload an Excel or CSV source and validate it before ingestion so that invalid data does not enter the workflow. | Source type and required fields are checked; valid and invalid row counts are shown. | Complete for initial contract |
| US-027 | As an Application Administrator, I want invalid rows isolated in quarantine so that valid rows can continue while errors are corrected. | Quarantine records retain row number, payload, reason and resolution status. | Complete |
| US-028 | As an Application Administrator, I want to resolve a corrected quarantine record so that the data can be reviewed again. | Resolution is audited and the record is no longer open. | Complete |
| US-029 | As an Application Administrator, I want a Fieldglass adapter and official mapping rules so that the production source is processed consistently. | Official Fieldglass sample is confirmed, mapped, validated and covered by integration tests. | Pending |
| US-030 | As an Application Administrator, I want generated exports for Fieldglass and NICE IEX so that downstream teams receive the expected templates. | Output templates, column mappings and validation reports are versioned. | Pending |

### 3.8 Publication, Backup and Recovery

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-031 | As a Master Administrator, I want to review the runtime snapshot before publication so that changes are intentional. | Publication shows pending items, current checksum and backup requirement. | In progress |
| US-032 | As a Master Administrator, I want a backup created before publication so that the previous state can be recovered. | Backup and manifest are created before the published snapshot changes. | Complete for governance flow |
| US-033 | As a Master Administrator, I want to restore a valid previous snapshot so that an operational mistake can be recovered safely. | Current state is backed up, checksum is validated and restore is audited. | Complete for governance flow |
| US-034 | As a Master Administrator, I want conflicting local and published snapshots detected so that one user's changes do not overwrite another user's work. | Conflict detection compares manifest/checksum and blocks unsafe publication. | Pending |

### 3.9 Audit and Governance

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-035 | As an Auditor, I want to view administrative events without editing them so that evidence remains trustworthy. | Audit events are append-only and original records are not edited or deleted. | Complete |
| US-036 | As a Master Administrator, I want to export and archive audit evidence so that it can support operational review. | JSON export and archive operations are available and audited. | Complete |
| US-037 | As a Master Administrator, I want a break-glass operation with a mandatory reason so that exceptional actions are controlled and explainable. | Operation, reason, actor and timestamp are recorded; access is role protected. | Complete |

### 3.10 Business Validation and Reconciliation

| ID | User story | Acceptance criteria | Status |
|---|---|---|---|
| US-038 | As an IAM Reviewer, I want workers within the 30-day rehire window flagged so that contracts requiring business review are not processed automatically. | The rule uses termination and start dates, records the reason and routes the worker to review. | Pending |
| US-039 | As an IAM Reviewer, I want blacklist or do-not-rehire matches flagged during onboarding so that restricted workers cannot be approved without an authorized decision. | The source list, match key, decision owner and override process are defined and audited. | Pending |
| US-040 | As an IAM Reviewer, I want active-worker status validated across source systems so that onboarding decisions use current worker data. | Fieldglass, AccessNow and vendor status are compared using an approved active-worker definition. | Pending |
| US-041 | As an administrator, I want contract and worker start/end dates validated so that onboarding aligns with the active agreement. | Date fields, timezone rules, invalid ranges and exception behavior are defined. | Pending |
| US-042 | As an IAM Team member, I want late Roster Lock submissions and missed onboarding milestones identified so that delays can be escalated before start date. | Submission deadlines, milestone dates, SLA thresholds and notification recipients are configurable. | Pending |
| US-043 | As an IAM leader, I want a centralized worker profile so that vendor, role, dates, manager, status and readiness are available in one place. | The canonical worker record, unique identifier and field ownership are approved. | Pending |
| US-044 | As an administrator, I want source precedence rules so that conflicting values are resolved consistently. | Precedence is defined per field and every override records the source and reason. | Pending |
| US-045 | As an IAM Analyst, I want Roster Lock, Fieldglass and Staffing Plan reconciled automatically so that discrepancies are visible without manual VLOOKUPs. | Missing, extra and mismatched workers produce categorized discrepancy records. | Pending |
| US-046 | As an administrator, I want Roster Lock and Fieldglass files detected and ingested from the synchronized workspace so that manual consolidation is reduced. | Approved folder, file naming, permissions and import schedule are defined. | Pending |
| US-047 | As an administrator, I want to preview proposed worker changes before publishing so that incorrect updates can be rejected safely. | Preview shows additions, updates, conflicts, quarantine rows and expected publication impact. | Pending |
| US-048 | As an IAM requester, I want controlled templates and required fields so that submissions are complete and consistent. | Template version, data dictionary, required columns and accepted values are visible to users. | Pending |
| US-049 | As an auditor, I want data lineage for each key worker value so that discrepancies can be traced to the source file and import batch. | Source system, file, row, import batch, timestamp and transformation are retained. | Pending |
| US-050 | As an IAM leader, I want offboarding compliance tracked so that access removal and billing stop risks are visible. | Termination notice, final production date, access removal, queue removal and invoice stop date are tracked. | Pending |
| US-051 | As an IAM administrator, I want validation and SLA failures notified to responsible users so that issues are corrected quickly. | In-app notifications are supported first; external channels and escalation ownership are confirmed before release. | Pending |
| US-052 | As an IAM leader, I want executive and operational dashboards so that workload, exceptions, SLA health and reconciliation outcomes are visible. | Metrics, ownership, refresh frequency and acceptance thresholds are approved. | Pending |

## 4. Screen and Navigation Inventory

### Desktop preflight

- **Environment Check:** SharePoint/OneDrive path, Access database, published SQLite, local runtime copy, folders, validation messages and startup log.
- **Browse / Retry:** Manual workspace selection and recovery after a failed validation.
- **Open App:** Opens the loopback browser login after the hard gate passes.
- **Stop Web App / Exit:** Controlled local process management from the PySide6 control panel.

### Web application

- **Sign in:** Application username and password; separate from the workstation identity gate.
- **Dashboard:** Current user, effective roles, workspace, request intake, administration, imports and notifications.
- **My Profile:** Username, roles and active workspace.
- **Notifications:** User notification list with read and resolve actions.
- **Command bar / Avatar:** Office-style navigation, notification counter, profile and sign out.

### Application Administration

- **Control Center:** Operational summary, unread notifications, active delegations and quick access.
- **Application Users:** Create and update application accounts, roles, status and password reset.
- **Windows Identities:** Register approved workstation identities and review pending discoveries.
- **Approval Queue:** Review, assign, approve or reject requests.
- **Delegations:** Create, expire, revoke and review temporary operating coverage.
- **Imports and Quarantine:** Upload source files, review batch results and resolve invalid records.
- **Publication Queue:** View approved changes waiting for controlled publication.
- **Notifications:** Manage administrative notifications.

### Master Administration

- **Security Administrators:** Manage Master and Application Administrators.
- **Roles and Permissions:** Review the global role matrix.
- **Global Settings:** Configure approval SLA, strict identity gate and break-glass availability.
- **Governance:** Review checksum, backups and publication/restore operations.
- **Audit Center:** View, export and archive administrative evidence.
- **Session Security:** Revoke active user sessions.

## 5. Configuration and Operational Rules

### Workspace configuration

The application requires a local synchronized SharePoint/OneDrive folder containing:

- the published Access database;
- the published runtime SQLite snapshot and manifest;
- local workspace, backup and audit folders;
- optional templates and exports folders.

The preflight does not silently create missing SharePoint resources. It reports the missing item and corrective action. The selected path is stored in user-local settings, outside the repository and outside SharePoint.

### Runtime data model

- **Local runtime SQLite:** primary working database for the local webapp and ORM services.
- **Published SQLite snapshot:** synchronized/published operational snapshot used at startup and publication boundaries.
- **Access database:** controlled secondary source and future interoperability target; the webapp does not write directly to the published Access file.
- **Audit and manifests:** integrity, publication and recovery evidence.

### Security rules

- Preflight is a hard gate before web login.
- Workstation identity and application account are separate concepts.
- Passwords are stored only as hashes; no password is displayed or persisted in plaintext.
- Backend authorization protects routes; hiding menu items is not considered authorization.
- Only Master Admin can manage Master Admin roles, global security settings, break-glass actions and recovery.
- The last active Master Admin and Application Admin cannot be removed or disabled.
- Administrative changes create audit events.

## 6. Help and Support Content

The stakeholder-facing help experience should be organized around the following short guides:

1. **Getting started:** Run the launcher, select the synchronized folder, resolve preflight errors and open the app.
2. **Signing in:** Understand the workstation identity gate versus the application account login.
3. **Submitting a request:** Select the request type, complete required fields and track status.
4. **Reviewing requests:** Assign a reviewer, approve/reject with notes and understand SLA escalation.
5. **Managing users and identities:** Create accounts, select roles, review discovered identities and protect administrator access.
6. **Handling notifications:** Read, resolve and follow notification links.
7. **Managing absence:** Create a scoped delegation, review expiration and process expired delegations.
8. **Importing files:** Upload Excel/CSV, interpret validation counts and resolve quarantine.
9. **Publishing and recovery:** Review checksum, create backup, publish or restore a snapshot.
10. **Audit and break-glass:** Export evidence and perform exceptional operations with mandatory reason.

The current application exposes the main workflows and operational messages. A dedicated in-app Help page and formal user acceptance guide remain delivery items for the next increment.

## 7. Stakeholder Scope Summary

### Delivered foundation

- Cross-platform local launcher and SharePoint preflight.
- Local SQLite runtime synchronized from the published snapshot.
- Separate workstation identity and application login.
- Flask/Waitress loopback webapp with PySide6 control panel.
- Bootstrap-based Kaiser Permanente branded interface.
- SQLAlchemy ORM persistence boundary.
- Role-aware navigation, user profile and notification center.
- User, Windows identity, request, approval, delegation, notification, audit and governance increments.

### Remaining before production ingestion

- Confirm the official Fieldglass export format with stakeholders.
- Define Fieldglass columns, mappings, required fields and sample files.
- Complete ingestion integration tests with representative Excel and Fieldglass data.
- Complete generated Fieldglass and NICE IEX templates/exports.
- Complete single-writer publication integration and snapshot conflict detection.
- Validate Windows Python 3.10 launcher and macOS development launcher.
- Complete user acceptance scenarios, help content and stakeholder sign-off.

## 8. Open Decisions

- Final Fieldglass source format and ownership of the official mapping.
- Final production strictness for approved workstation identities.
- Final role/permission matrix and segregation-of-duties rules.
- SLA targets and escalation recipients by request type.
- Quarantine correction ownership and retention period.
- Access publication cadence and backup retention policy.
- Whether the future SharePoint integration will use external authentication or remain local-sync based.
