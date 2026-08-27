# Master Roster — Functional Requirements and Read-only Scope

**Status:** Requirements documented; implementation not started  
**Date:** 2026-08-27  
**Priority:** Next planning increment  
**Planned branch:** `feature/master-roster-read-only`  
**Source:** IAM Automation Touchpoint summary supplied by the stakeholder; source transcript and final business rules require confirmation.

## Objective

Add Master Roster as an independent source of employee evidence and provide
read-only comparison, duplicate, conflict, history and export capabilities
without changing the canonical employee in the current phase.

## Current phase boundary

The active product phase is **Read-only Employee & Evidence Review**.

In this phase the system may detect, stage, compare, display and export Master
Roster observations. It must not promote Master Roster data into the canonical
employee, merge workers, approve changes, update Access, publish SQLite or
execute downstream Data Loader operations.

Consolidation and canonical updates are future controlled-change capabilities.

## Functional requirements

### RF-001 — Automatic Master Roster intake

Detect new or changed Master Roster files in the configured SharePoint-synced
folder and register each file with checksum, timestamp and processing status.

### RF-002 — Independent source registration

Represent `MASTER_ROSTER` as an independent source system with source-file,
batch, row and field lineage. The source must remain distinguishable from
AccessNow, Fieldglass, Roster Lock and future sources.

### RF-003 — Canonical employee evidence enrichment preview

For each Master Roster row, show the likely canonical employee match and the
proposed enrichment as a read-only comparison. No canonical update occurs.

### RF-004 — Multi-source consolidation view

Display the available values from Master Roster, AccessNow, Fieldglass,
Roster Lock and other configured sources together while preserving source
ownership and lineage.

### RF-005 — Duplicate detection

Identify possible duplicates using name, email, UID/NID, Employee ID and
cross-source identity signals. Matching rules must expose the signal and
confidence used for each candidate.

### RF-006 — Duplicate review states

Display candidate, reviewed, merged, unresolved and conflict states where
those states already exist in the evidence model. Confirming or merging a
duplicate is future-phase functionality; the current phase only records or
displays review evidence.

### RF-007 — Duplicate exports

Export duplicate results to CSV and XLSX with stable columns, source evidence,
identifiers, status, conflicts and recommendation.

### RF-008 — Repeated-identifier exports

Export repeated identifiers found during matching, including identifier type,
normalized value, affected source records, affected workers and review state.

### RF-009 — Employee change timeline

Display the chronological timeline of known employee profile observations and
approved historical changes, clearly distinguishing observed, staged and
applied events.

### RF-010 — Source-level change detail

For each displayed change, show source, source file, update timestamp, field,
previous value, incoming value and review/application state.

### RF-011 — Processed-file history

Allow authorized users to trace an observation or displayed change back to the
file, checksum, batch, row and source adapter that produced it.

### RF-012 — Consecutive Master Roster comparison

Compare consecutive Master Roster versions and identify new employees,
terminations, attribute changes and information updates as read-only review
items.

### RF-013 — Conflict view

Present conflicts between Master Roster and other sources, including the
current value, incoming value, source precedence decision if known, and review
state.

### RF-014 — Business review workspace

Provide a non-technical review workspace for searching, filtering and
exporting additions, changes, duplicates, conflicts and unmatched records.
Resolution actions remain disabled until the controlled-change phase.

### RF-015 — Extensible source adapter contract

Define a source adapter contract so future sources can be added without
redesigning the canonical evidence and lineage model.

## Non-functional requirements

- **RNF-001 Scalability:** support additional sources without changing the core evidence model.
- **RNF-002 Performance:** process and compare files within agreed operational limits.
- **RNF-003 Integrity:** never discard source evidence during staging or comparison.
- **RNF-004 Auditability:** record detection, staging, report generation and review evidence.
- **RNF-005 Traceability:** every displayed value must be traceable to source file and row where available.
- **RNF-006 Usability:** business users can review conflicts and duplicates without technical intervention.
- **RNF-007 Maintainability:** mappings and matching rules are configurable where practical.
- **RNF-008 Availability:** one unavailable source must not prevent review of available sources.
- **RNF-009 Consistency:** the same canonical worker identity is used for cross-source display.
- **RNF-010 Exportability:** critical analysis views support CSV and XLSX evidence export.

## Acceptance criteria for the current phase

- Master Roster files are detected and registered without modifying canonical employees.
- Source records remain independently identifiable as `MASTER_ROSTER`.
- Users can view matched, unmatched, duplicate and conflicting records with lineage.
- Consecutive-file comparison identifies additions, terminations and changes.
- Duplicate and repeated-identifier reports export the filtered read-only result.
- Timeline and source-detail views distinguish observation from applied change.
- No current-phase action can approve, merge, promote, update or publish employee data.
- Unconfirmed business rules, mappings and ownership decisions are visible in the backlog.

## Decisions required before implementation

- Confirm the official Master Roster file name, folder, owner and delivery cadence.
- Confirm workbook sheets, headers, row boundaries and required fields.
- Confirm the canonical matching identifiers and precedence order.
- Confirm how termination and rehire records are represented.
- Confirm duplicate thresholds, confidence levels and review ownership.
- Confirm retention, legal-hold and export-evidence requirements.
- Confirm whether future consolidation is manual, approved workflow or writer batch.

## Future controlled-change scope

The following are intentionally deferred:

- Promote a Master Roster row into a canonical employee.
- Apply enrichment or lifecycle changes to a canonical employee.
- Confirm or merge duplicate workers.
- Approve or publish changes to runtime SQLite or Access.
- Generate or execute downstream Data Loader submissions.

