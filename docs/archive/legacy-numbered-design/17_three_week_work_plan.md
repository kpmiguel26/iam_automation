# Three-Week Work Plan

> **Current phase note — 2026-08-27:** The original three-week plan includes
> future writer and publication capabilities. The active release has been
> narrowed to **Read-only Employee & Evidence Review**; those capabilities are
> deferred and must not be treated as current acceptance scope.

## Project Capacity

- Duration: 3 weeks
- Schedule: 4 hours per day, 5 days per week
- Total capacity: 60 hours
- Delivery model: MVP with controlled scope, integration tests, failure tests, and user acceptance testing.
- Architecture baseline: Python 3.10, Microsoft Access master snapshot, immutable JSON change requests, single-writer administrator workflow, SharePoint/OneDrive document sync, Excel ingestion, and Excel template export.

## Scope Assumptions

- The project will deliver a working MVP, not every future enterprise-system integration.
- Fieldglass is the primary template/import/export target for the first release.
- Salesforce and NICE IEX exports should be scaffolded through reusable mapping/configuration, with at least one additional template proven if time permits.
- Access remains the master snapshot. Ordinary users do not write directly to the published `.accdb`.
- All master-data changes go through request, approval, application, audit, and publication workflow.

## Kanban-Ready Work Plan

The Smartsheet-ready import is available in [`docs/17_smartsheet_kanban_import.csv`](./17_smartsheet_kanban_import.csv). It contains one parent row per deliverable and three executable subtasks per deliverable. Use `Parent ID` and `Level` to create the hierarchy after import; use `Status` as the Kanban card status and update it as work moves through the board.

| ID | Week | Phase Alignment | Deliverable | Work Item | Est. Hours | Acceptance Criteria |
| --- | ---: | --- | --- | --- | ---: | --- |
| 1 | 1 | Phase 0-2 | Scope & Architecture Baseline | Confirm updated end-to-end workflow, MVP boundaries, Python 3.10 constraint, SharePoint folder model, and single-writer/no-direct-client-write rule | 2 | Architecture notes match the new onboarding flow and identify source of truth, owners, and constraints |
| 2 | 1 | Phase 2 | Configuration & SharePoint Paths | Define runtime config for SharePoint/OneDrive folders: incoming roster, templates, pending requests, imported, quarantine, exports, archive, manifests, and Access snapshot | 2 | Config validates all required paths and reflects the SharePoint route used by the automation |
| 3 | 1 | Phase 1, 4, 6, 7 | Template Inventory & Verification | Review roster lock, Fieldglass, NICE IEX, and agent creation templates; record required sheets, headers, mandatory fields, owner, and validation rules | 4 | Template inventory and validation checklist are complete enough to drive ingestion/export coding |
| 4 | 1 | Phase 5, 9 | Access & Master Roster Data Model | Finalize Access schema for employees, workers, roles, approvals, requests, audit events, batches, versions, vendors, LOBs, skills, template mappings, export runs, and agent lifecycle | 3 | Data model supports roster conversion, NUID tracking, post-onboarding updates, audit, and governance |
| 5 | 1 | Phase 1-3 | Excel Ingestion Foundation | Build reusable Excel reader/validator for roster files and templates using OpenPyXL | 4 | Reads configured workbook/sheet/header layouts and returns normalized rows plus row-level validation errors |
| 6 | 1 | Phase 1-4 | Fieldglass Ingestion POC | Ingest the roster lock/Fieldglass-ready Excel input into normalized staging data | 3 | Sample input produces validated staging records for worker creation and downstream master roster updates |
| 7 | 1 | Phase 3, 9 | User Validation & Roles | Implement Windows username capture and role validation for requester, reviewer, writer/admin, auditor, and monitor roles | 2 | Unauthorized users are blocked and role permissions are enforced before workflow actions run |
| 8 | 2 | Phase 8 | CRUD Request Workflows | Implement create, update, deactivate, and view/search workflows as immutable request-driven operations for agent lifecycle changes | 4 | CRUD actions generate valid requests and never directly modify the master Access snapshot |
| 9 | 2 | Phase 2-3 | Admin Import, Idempotency & Quarantine | Import pending requests and inbound files, detect duplicates, maintain processed registry, and quarantine invalid inputs | 3 | Duplicate request/file IDs are rejected safely; malformed files move to quarantine with reason captured |
| 10 | 2 | Phase 3-4 | Approval Workflow | Implement review, approve, reject, conflict, and decision notes for onboarding and post-onboarding requests | 3 | Reviewer/admin decisions are recorded; segregation rules prevent unauthorized self-approval when enabled |
| 11 | 2 | Phase 4-5 | Apply Approved Changes | Apply approved requests to a local Access working copy with record-version checks, referential validation, NUID fields, and status transitions | 4 | Matching versions apply; stale versions become conflicts; invalid references fail cleanly |
| 12 | 2 | Phase 5 | Master Roster Creation & Enrichment | Convert validated Fieldglass/onboarding data into the official master roster and enrich NUID, status, training/nesting/production, and timeline indicators | 2 | Master roster records are generated or updated with required enrichment fields |
| 13 | 2 | Phase 4, 9 | Audit / Bitacora | Write audit events for ingest, validation, request creation, approval, rejection, apply, conflict, export, publish, failure, and recovery | 2 | Audit records include actor, role, computer, request ID, batch ID, entity, result, timestamp, and error details |
| 14 | 2 | Phase 4, 7 | Fieldglass Worker Creation / Export | Generate the Fieldglass worker creation or load file from approved/applied data using configured template mappings | 2 | Output workbook preserves template structure and passes required-field/header validation |
| 15 | 3 | Phase 6-7 | NICE IEX Configuration & Agent Creation Package | Generate or scaffold NICE IEX hierarchy/profile export package from master roster data, including vendor, LOB, skills, queues, and configuration rules | 3 | NICE IEX package is generated or documented with exact blockers and required manual fields |
| 16 | 3 | Phase 8-9 | Snapshot Publication, Recovery & Governance | Implement versioned Access snapshot publication, checksum/manifest, archive rules, failed-batch recovery, and reconciliation report | 3 | Publish creates versioned snapshot and manifest; failed batches can be retried without duplicate application |
| 17 | 3 | All phases | Integration Tests | Test happy path from roster intake through validation, Fieldglass, master roster, IEX package/export, audit, and publication | 4 | End-to-end scenario passes with repeatable sample data |
| 18 | 3 | All phases | Failure & Security Tests | Test bad Excel, missing headers, duplicate file/request, unauthorized user, stale version, failed export, checksum mismatch, and recovery | 3 | Failures route to expected status/folder and produce audit events with actionable error details |
| 19 | 3 | Phase 0-9 | User Acceptance Testing | Run UAT with WFM/requester, vendor input, IAM/access management, KP approver, admin/writer, and auditor/monitor scenarios | 4 | UAT checklist is completed; defects and follow-up items are logged and prioritized |
| 20 | 3 | Phase 9 | Documentation, Demo & Handoff | Update user/admin/recovery docs, template mapping notes, test evidence, known risks, and final demo package | 3 | Handoff package is ready and Smartsheet/Kanban items can be closed or moved to next-phase backlog |

## Suggested Kanban Columns

- Backlog
- Ready
- In Progress
- Code Review / Validation
- Testing
- UAT
- Done
- Blocked

Recommended initial status for all imported rows: `Backlog`. The parent deliverable should be considered complete only when all child subtasks are `Done` and the parent acceptance criterion is met.

## Suggested Smartsheet Fields

- ID
- Week
- Deliverable
- Work Item
- Owner
- Status
- Estimate Hours
- Actual Hours
- Dependency
- Acceptance Criteria
- Risk / Blocker
- Notes

## Weekly Milestones

### End of Week 1

Foundation is complete:

- Python 3.10 baseline verified.
- Access schema proposal is ready.
- SharePoint/local workspace configuration is ready.
- Template inventory and mapping design are drafted.
- Excel ingestion foundation and Fieldglass ingestion POC are working.
- Identity and role validation are in place.

### End of Week 2

Core workflow is working:

- Request-driven CRUD flow exists.
- Pending request import, duplicate handling, quarantine, approval, rejection, and conflict handling are implemented.
- Approved changes can be applied to a local Access working copy with record-version validation.
- Bitacora/audit events are written.
- Fieldglass export is generated from applied data.

### End of Week 3

MVP is validated and ready for demo:

- Additional export path is scaffolded or validated.
- Versioned Access snapshot and manifest publication logic exists.
- Recovery and reconciliation flow is documented and tested.
- Integration tests, failure tests, and UAT are completed.
- Documentation and handoff package are ready.

## Definition of Done

- Code runs on Python 3.10.
- Tests pass.
- Excel ingestion validates templates, headers, required fields, and row-level errors.
- Fieldglass ingestion and export path is proven.
- At least one additional export path is scaffolded or validated.
- No direct client write path exists for the master Access database.
- CRUD operations are request-driven and approval-controlled.
- Requests are immutable JSON files.
- Admin workflow is idempotent.
- Audit/bitacora event exists for every meaningful action.
- Versioned Access snapshot and manifest logic exists.
- Integration and failure tests are documented.
- UAT feedback is recorded.
- User-facing and admin-facing documentation is updated.

## Explicit Out of Scope for the 60-Hour MVP

- A central API, server, Windows Service, persistent VM, Docker deployment, SQL Server, PostgreSQL, Redis, or cloud database.
- Full production-grade UI polish for every screen.
- Full automation for every future enterprise system.
- Strong centralized authentication beyond Windows username plus approved-user role validation.
- Cryptographic immutability of JSONL/audit logs unless a later security phase adds signing or hash chaining.
