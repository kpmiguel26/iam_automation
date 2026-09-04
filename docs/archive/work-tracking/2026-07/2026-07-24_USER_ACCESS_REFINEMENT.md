# Work Session: User and Access Refinement

> **Historical record — 2026-07-24.** Current status is maintained only in
> [`../../../STATUS.md`](../../../STATUS.md).

**Date:** 2026-07-24  
**Project:** IAM Automation  
**Branch:** `feature/iam-data-ingestion-foundation`  
**Status:** Ready for refinement  
**Dependency:** Official Fieldglass, Roster Lock and downstream template formats are expected next week.

## Objective

Refine the user and access model before data ingestion begins. This work must remain independent of any official source-file format so the approved contracts can be connected later without redesigning authentication, authorization or user lifecycle behavior.

## Scope For Today

- Clarify the difference between the local Windows identity gate and the IAM application account.
- Refine the user lifecycle and account states.
- Confirm the human-readable role catalog and permission boundaries.
- Refine Master Admin and Application Admin behavior.
- Define identity discovery and approval behavior.
- Confirm reviewer, approver and delegation continuity rules.
- Confirm notification ownership and user-facing status.
- Prepare the user/access acceptance checklist for stakeholder review.

## Deliverables

| ID | Deliverable | Status | Owner | Evidence / Notes |
|---|---|---|---|---|
| UA-01 | User and access domain glossary | TODO | IAM team | Define Windows identity, application account, worker identity and session. |
| UA-02 | Role and permission matrix | TODO | IAM team / stakeholders | Confirm `MASTER_ADMIN`, `APPLICATION_ADMIN`, `REQUESTER`, `REVIEWER`, `WRITER` and `AUDITOR`. |
| UA-03 | User lifecycle rules | In progress | IAM team / stakeholders | Controlled account states are implemented; recovery and rehire behavior remain stakeholder decisions. |
| UA-04 | Windows identity traceability flow | Completed | IAM team | Preflight records username and computer; application login owns authorization. |
| UA-05 | Application account rules | TODO | IAM team | Password hash, reset, session, lockout and active status. |
| UA-06 | Administrator protection rules | TODO | IAM team | Last active Master/Admin protection and self-demotion rules. |
| UA-07 | Reviewer and delegation rules | TODO | IAM team / stakeholders | Assignment, absence, expiration, reassignment and escalation. |
| UA-08 | Notification ownership matrix | TODO | IAM team | Recipient, severity, lifecycle, expiry and target route. |
| UA-09 | User/access UAT checklist | TODO | QA / stakeholders | Positive, negative, recovery and authorization scenarios. |
| UA-10 | Architecture and backlog update | TODO | IAM team | Record decisions in `CURRENT_PLAN.md`, `BACKLOG.md` and `BITACORA.md`. |

## Domain Decisions To Confirm

### 1. Identity layers

| Layer | Purpose | Stored in | Can authenticate? |
|---|---|---|---|
| Windows identity | Confirms the person operating the VDI or workstation. | Approved identity records in local SQLite and synchronized snapshot. | No application password. It is the preflight gate. |
| Application account | Confirms access to IAM Automation after preflight. | Local runtime SQLite through the ORM. | Yes, with username and password hash. |
| Worker / business identity | Represents the person being onboarded or managed by the process. | Ingestion domain, to be finalized after official formats. | No. It is business data, not a login account. |
| Local session | Maintains the authenticated application context. | Runtime session store and audit events. | No. It is created after application login. |

### 2. Account states

The application should use controlled states instead of free text:

- `PENDING`: created but not yet usable.
- `ACTIVE`: may sign in when the Windows identity gate also passes.
- `SUSPENDED`: temporarily blocked without deleting history.
- `PASSWORD_RESET_REQUIRED`: account remains present but must complete reset flow.
- `INACTIVE`: no longer allowed to sign in.
- `RECOVERY_PENDING`: awaiting administrator recovery action.

Open decision: confirm whether `PENDING` and `RECOVERY_PENDING` are needed in the first production release or can remain reserved for the next increment.

### 3. Role language

The UI must show human-readable labels while the database and authorization layer use stable role keys:

| Technical key | UI label | Boundary |
|---|---|---|
| `MASTER_ADMIN` | Master Administrator | Full security, recovery, role and break-glass control. |
| `APPLICATION_ADMIN` | Application Administrator | Daily users, approvals, ingestion, quarantine and operational publication. |
| `REQUESTER` | Requester | Creates and tracks own requests. |
| `REVIEWER` | Reviewer | Reviews assigned requests and records decisions. |
| `WRITER` | Data Publisher | Executes approved single-writer publication steps. |
| `AUDITOR` | Auditor | Reads and exports audit evidence without changing original events. |

Temporary compatibility alias: `ADMINISTRATOR` maps to `APPLICATION_ADMIN` until migration is complete.

## Refinement Checklist

### User lifecycle

- [x] Define required fields for an application user: username, display name, status, roles, created by, timestamps and last activity.
- [x] Persist controlled application-account status in SQLite and expose it through the ORM/domain model.
- [x] Use `ACTIVE` as the only status accepted by application login.
- [x] Replace the admin UI boolean status selector with controlled status options.
- [ ] Confirm whether email or contact information is required for notifications.
- [ ] Confirm password policy, reset behavior and whether lockout is required now.
- [ ] Confirm whether an inactive account can retain pending requests.
- [ ] Confirm how a reactivated account receives or regains assigned work.
- [ ] Confirm that user deletion is logical deactivation only; audit history remains immutable.

### Windows identity

- [x] Define normalized identity format for Windows, VDI and macOS development.
- [x] Define duplicate detection rules, including case normalization.
- [x] Record the detected username and computer in append-only audit evidence.
- [x] Keep the Windows identity out of application-account authorization.
- [x] Confirm that application-account credentials remain separate from workstation identity.
- [ ] Decide whether the legacy identity-discovery JSON should be retired or retained only as an operational trace.

### Roles and authorization

- [ ] Confirm permissions by route and action, not only by menu visibility.
- [ ] Confirm whether `MASTER_ADMIN` can assign every operational role.
- [ ] Confirm whether `APPLICATION_ADMIN` can assign `REVIEWER`, `WRITER` and `AUDITOR`.
- [ ] Block self-removal of the last active `MASTER_ADMIN`.
- [ ] Block self-removal of the last active `APPLICATION_ADMIN`.
- [ ] Record all role and status changes as immutable audit events.
- [ ] Confirm whether permission changes require explicit publication or are immediate in local SQLite.

### Reviewers, delegations and continuity

- [ ] Define manual reviewer assignment and reassignment permissions.
- [ ] Define delegation scope: approvals, ingestion, publication or full operations.
- [ ] Define start/end timestamps and timezone handling.
- [ ] Define behavior for pending requests when a delegation expires.
- [ ] Define SLA warning and escalation thresholds.
- [ ] Define the fallback owner when the assigned reviewer and delegate are unavailable.

### Notifications

- [ ] Confirm notification recipients for pending identity discovery.
- [ ] Confirm notification recipients for new requests, reassignment and overdue SLA.
- [ ] Confirm severity labels: information, warning, action required and critical.
- [ ] Confirm read, resolved and expired transitions.
- [ ] Confirm expiration policy and retention period.
- [ ] Confirm whether email or Teams delivery is out of scope until the official operating model is approved.

## User/Access Acceptance Scenarios

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| UAT-UA-01 | Approved Windows identity, active application account and valid password | User reaches the dashboard with assigned roles. | TODO |
| UAT-UA-02 | Approved Windows identity, invalid application password | Login is rejected without revealing which credential failed. | TODO |
| UAT-UA-03 | Unapproved Windows identity | Preflight blocks application login and records the reason. | TODO |
| UAT-UA-04 | Inactive application account | Application login is rejected and an audit event is recorded. | TODO |
| UAT-UA-05 | Application Admin opens Master-only route | Backend returns an authorization failure; route is not merely hidden. | TODO |
| UAT-UA-06 | Master Admin assigns an operational role | Role appears with a human-readable label and stable technical key. | TODO |
| UAT-UA-07 | Admin attempts to remove the last Master Admin role | Operation is blocked with a clear message and audit evidence. | TODO |
| UAT-UA-08 | Reviewer becomes unavailable | Admin can assign a scoped temporary delegate. | TODO |
| UAT-UA-09 | Delegation expires with pending requests | Requests are retained, escalated or reassigned according to the configured rule. | TODO |
| UAT-UA-10 | New identity is discovered locally | Admin receives an in-app notification and can approve or reject it. | TODO |
| UAT-UA-11 | Session is revoked by Master Admin | Subsequent requests require a new application login. | TODO |
| UAT-UA-12 | User signs out and signs in again | Session is replaced cleanly and no previous role context leaks. | TODO |

## Out Of Scope Until Next Week

- Final Fieldglass column mapping.
- Final Roster Lock column mapping.
- Official templates and downstream export contracts.
- Final source precedence for conflicting business fields.
- Production WFM lifecycle requirements.
- External AD, email, Teams or SharePoint authentication integration.

## Exit Criteria

This work session is complete when:

1. Stakeholders approve the identity-layer glossary.
2. The role matrix has an owner for every protected action.
3. Account and identity lifecycle states are documented.
4. Delegation and notification rules have a defined fallback path.
5. The UAT scenarios are ready to execute.
6. The open decisions are recorded without inventing source-file formats.
7. The backlog and bitacora reference this document.

## Next Step

After this refinement is reviewed, continue with the ingestion foundation on the same feature branch. Connect the approved Fieldglass and Roster Lock contracts to the existing user, reviewer, notification, audit and publication controls only after the formats are officially provided.
