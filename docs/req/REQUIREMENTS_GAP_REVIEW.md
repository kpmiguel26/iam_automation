# IAM Automation Requirements Gap Review

**Source:** `IAM Automation Software Requirements Tracker.xlsx`  
**Source commit:** `21d8fff` (`requeriments`)  
**Review date:** 2026-07-24  
**Compared against:** `feature/admin-control-center`

## Executive Summary

The requirements tracker is a broad business and technical baseline containing 61 requirements across business rules, timing, source-of-truth, reconciliation, workflow, security, governance, reporting, data management and integrations.

The spreadsheet marks all requirements as `Pending`. This is treated as a requirements baseline, not as a reliable implementation status. The current prototype has already delivered a number of platform capabilities that should be reflected in the tracker after stakeholder validation.

The next major delivery gate is data ingestion. Before implementing production ingestion, the team must confirm the official Fieldglass report, the Roster Lock template, field ownership, source precedence and the business rules that determine review, quarantine and approval.

## Requirements Already Represented in the Prototype

These requirements have a working foundation or a partial implementation:

| Requirement area | Current evidence | Qualification |
|---|---|---|
| Duplicate request prevention | Request service and stable request IDs | Application request duplication is covered; duplicate worker identity logic remains to be defined. |
| Mandatory field validation | Initial CSV/XLSX import contract | Required fields are currently limited and must be expanded using the approved data dictionary. |
| File validation | Import validation and batch history | Initial validation exists; official Fieldglass and Roster Lock rules remain pending. |
| Exception handling | Quarantine records and resolution workflow | Quarantine exists; conflict categories and business resolution rules remain pending. |
| Approval and rejection | Approval queue, reviewer assignment and decisions | Business status names and decision reason codes require confirmation. |
| Request states | Pending, review, approval and publication queue states | Full business lifecycle must include the agreed `Under Review`, `Quarantine` and `Published` states. |
| Single-writer model | Local SQLite, publication queue, backup and checksum governance | Controlled publication integration and conflict blocking remain to be completed. |
| Draft vs. published separation | Local runtime and published SQLite snapshot | Publication manifest and synchronization rules need final acceptance. |
| Versioning and recovery | Backups, manifests, checksums and restore flow | Retention, ownership and conflict recovery policy remain open. |
| Roles and dual authentication | Master/Application Admin, operational roles, preflight identity and app login | Final permission matrix and production identity policy remain open. |
| Delegated permissions | Scoped, expiring delegations and queue reassignment | Approval and expiration policy needs stakeholder sign-off. |
| Audit and decision history | Append-only audit events, export and archive | Device tracking, retention and formal compliance requirements remain open. |
| SLA and notifications | SLA settings, overdue escalation and in-app notifications | Targets, recipients and email/Teams channel are not finalized. |
| Backups and SharePoint structure | Local runtime copy, backup/audit folders and preflight | Production folder ownership and permissions must be confirmed. |
| Web interface | Flask/Waitress local webapp with Bootstrap UI | Future scalability path exists; production hosting decision is open. |

## High-Priority Gaps Before Production Ingestion

### 1. Business validation rules

The following rules are not implemented and require business definitions and test examples:

- 30-day rehire policy validation.
- Blacklist or do-not-rehire validation.
- Active-worker validation across Fieldglass, AccessNow and vendor sources.
- Contract start/end date validation.
- NPN validation before enrollment.
- Roster Lock submission deadline and late-submission handling.
- Fieldglass acceptance timing before formal start.
- Missed onboarding milestone alerts.

Each rule needs an owner, input fields, decision outcome, severity, quarantine behavior and test cases.

### 2. Source of truth and data lineage

The tracker requires a centralized worker record fed by Roster Lock, Master Roster, Fieldglass, Staffing Plan, AccessNow, Salesforce, CXOne and NICE IEX. Before ingestion, stakeholders must approve:

- canonical worker identifier;
- vendor identifier and hierarchy;
- field-level source ownership;
- source precedence when values conflict;
- effective dating and historical retention;
- lineage metadata for each imported value;
- conflict and quarantine rules.

The current SQLite ORM is a suitable working persistence boundary, but the worker aggregate and source-lineage model still need to be designed.

### 3. Official source formats

The current application supports an initial CSV/XLSX contract, but it is not yet the official Fieldglass adapter. The next implementation should wait for approved samples and define:

- exact Fieldglass export name and version;
- required and optional columns;
- data types and accepted values;
- date/time and timezone rules;
- duplicate key;
- vendor and worker status mapping;
- change detection behavior;
- output template for downstream systems.

The same exercise is required for Roster Lock, Staffing Plan and headcount files.

### 4. Reconciliation

The following comparisons are required and are not yet implemented as production workflows:

- Roster Lock versus Fieldglass.
- Roster Lock versus Staffing Plan.
- Fieldglass versus AccessNow.
- Vendor discrepancy reporting by vendor, issue type and action required.
- Weekly reconciliation report across Roster Lock, Fieldglass, Staffing Plan and headcount.

These should use reusable matching rules and produce reviewable discrepancy records rather than one-off exports.

### 5. Downstream integrations and reporting

The tracker includes Salesforce profile creation, CXOne profile creation and NICE IEX configuration tracking. These are currently scope items, not implemented integrations.

Reporting requirements also remain open:

- executive dashboard;
- operational dashboard;
- offboarding compliance report, including the discussed 48-hour monitoring;
- vendor and reconciliation metrics;
- SLA compliance and exception trends.

## Recommended Delivery Sequence

1. Confirm Fieldglass and Roster Lock official samples with stakeholders.
2. Create the source data dictionary and field ownership matrix.
3. Define the canonical worker profile and source-lineage model in SQLite ORM.
4. Implement reusable validation rules for mandatory fields, dates, active worker, rehire and blacklist checks.
5. Implement Fieldglass ingestion with preview, duplicate detection and quarantine.
6. Implement Roster Lock ingestion and source reconciliation.
7. Add discrepancy queues, business review status and decision reason codes.
8. Add generated exports for Fieldglass/NICE IEX and controlled publication integration.
9. Add executive/operational dashboards and offboarding compliance reporting.
10. Run integration tests, Windows/macOS validation and stakeholder UAT.

## Decisions Required From Stakeholders

- What is the official Fieldglass report and who owns its mapping?
- What is the canonical worker identifier across all systems?
- Which system owns each key worker field?
- What is the precedence rule for conflicting values?
- What exact rule defines an active worker?
- How is the 30-day rehire window calculated and who may override it?
- What is the approved blacklist source and review process?
- Which milestones and SLA thresholds generate alerts?
- Which notification channel is required beyond in-app notifications?
- Which integrations are MVP versus future scope: AccessNow, Salesforce, CXOne, NICE IEX and ServiceNow?
- What retention policy applies to runtime snapshots, backups, quarantine records and audit evidence?

## Tracker Status Recommendation

The spreadsheet should be updated after the next requirements workshop using these statuses:

- `Complete`: implemented and covered by tests/evidence.
- `In Progress`: implementation exists but integration or acceptance is incomplete.
- `Pending`: requirement is agreed but implementation has not started.
- `Dependency`: blocked by a source file, system access, business rule or owner decision.
- `Future`: intentionally outside the current MVP.

The current prototype should not be declared production-ready solely because the platform foundation is complete. The main remaining risk is not the web shell; it is the correctness and ownership of the worker data entering the workflow.
