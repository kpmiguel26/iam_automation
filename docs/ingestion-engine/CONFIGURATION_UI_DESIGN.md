# Configuration UI Design

**Status:** Persisted template library implemented; runtime activation remains out of scope

**Date:** 2026-09-22

**Related architecture:** [Ingestion Engine Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)

## 1. Purpose

This prototype validates the future source-configuration workflow before any
production ingestion lifecycle is changed. It lets an administrator describe a
source schema, choose imported columns, configure inferred data types and
structural validation expectations, declare the source's identity authority,
then test a bounded sample in memory.

The page saves versioned draft snapshots in SQLite and offers a separate
template library for continuing configuration and approval. These records are
configuration evidence only: they do not activate a watcher or invoke the
existing orchestrator.

## 2. User workflow

```text
READ FILE -> REVIEW RAW STRUCTURE -> COMPOSE HEADERS -> REVIEW DATA -> SELECT COLUMNS -> DECLARE IDENTITY AUTHORITY -> CHECK DRAFT
```

- **READ FILE:** upload a bounded CSV/XLSX sample; the file is held in memory only.
- **REVIEW RAW STRUCTURE:** for Excel, select the worksheet and inspect a bounded
  raw grid with row numbers and column positions.
- **COMPOSE HEADERS:** select one primary header row or multiple context rows.
  Selected values are composed per column, so `NUID` + `LogonID` and `NPN` +
  `LogonID` remain distinguishable. The suggested draft field name is editable.
- **REVIEW DATA:** show the selected headers and a small sample beginning after
  the selected header region before asking the administrator to make configuration
  decisions.
- **SELECT COLUMNS:** decide which source columns belong in the draft schema,
  review the inferred data type and change it when needed. The UI also offers a
  human-readable cleanup recommendation based on explainable source-column
  signals; the administrator can keep it, choose another option or leave the
  value unchanged.
- **DECLARE IDENTITY AUTHORITY:** first choose in plain language whether the
  report may introduce new employees, may only help find existing employees,
  or is evidence only. The draft shows the corresponding Identity Seed,
  Identity Enrichment or Evidence Only contract role. Identity Seed has a
  separate source-level permission to propose Employee UUIDs. Then, for each
  included field, the administrator can allow identity matching and classify
  the field as Strong or Supporting. A field can authorize creation only when
  it is included, marked for identity matching, classified Strong, and the
  source-level permission is enabled. Templates that only link or validate
  existing employees need at least one Strong matching field. A template
  authorized to create Employee UUIDs needs at least two distinct Strong fields,
  both selected for matching and creation. Identity Seed without creation
  permission still needs one Strong matching field; Evidence Only is exempt.
  Identity fields remain strings so leading zeroes are preserved. This is
  source governance, not Employee/canonical field mapping. The laboratory allows
  at most three fields for identity matching; the counter is visible and
  remaining choices are disabled after the third selection.
- **CHECK DRAFT:** run structural checks and a normalized preview in memory.

The interaction is server-rendered with HTMX partial swaps and retains normal
form actions as a full-page fallback. This keeps the screen approachable for
Business Rules users while preserving explicit loading, error and empty states.

Advanced source identity, reader hints, validation constraints and drift severity
remain available in a disclosure after the guided flow; they are not the first
thing a user must understand.

The template library lists draft and approved versions. Administrators can
continue a draft, approve a valid draft, or create a new draft from an approved
version. Approved versions are immutable. There is no Activate, Publish, Enable
watcher or Run ingestion action.

## 3. Draft contract

The typed contracts live in `iam_automation/application/ingestion/`:

- `DraftSourceDefinition`
- `DraftReaderSettings`
- `DraftRecognitionSettings`
- `DraftFieldDefinition`
- `DraftIdentityGovernance` and `DraftIdentityIdentifier` describe the draft's
  authority over identity. They reference the source-schema `field_key`; they
  do not create or resolve an Employee UUID.
- `DraftFieldMapping` remains only as a compatibility contract for older callers;
  this screen does not populate canonical or employee mappings.
- `DraftValidationDefinition`

The contract remains a draft-only UI contract serializable to JSON and the Flask
session. SQLite stores versioned snapshots of this contract in
`source_definition_versions`; it is not yet the runtime `SourceDefinition` or
`SourceRegistry` contract.

Identifiers are represented as strings. Values such as `001234` are never coerced
to integers by the sample inspector. Raw composed header identity remains
separate from the editable draft field key. Identity authority is never inferred
as an active decision: the screen provides explainable hints, but the user must
select the role and permissions.

## 4. Validation and preview behavior

The preview service supports CSV and XLSX samples with a 20 MB upload limit, at
most 5,000 inspected rows and at most 25 displayed rows. Excel sheet names, raw
rows and selected header ranges are reported. Type inference is a suggestion
only and never changes the draft automatically.

Preview diagnostics include unknown fields, missing required/optional fields,
invalid configured values, included/excluded source columns and normalized sample rows.
Transforms are an explicit allow-list; arbitrary Python is never evaluated. The
  recommendation is assistive only: identifiers preserve leading zeroes, emails
  are suggested for lowercase trimming, dates are prepared for validation and
  ordinary text defaults to keeping the source value as provided.

## 5. Isolation guarantees

The configuration library:

- stores draft and approved template snapshots in an additive SQLite table;
- keeps the current editing pointer in the signed Flask session;
- records the actor and timestamps for creation, edits and approval;
- preserves approved versions and starts a new version when further configuration is needed;
- does not use the governed employee-field catalog for source selection;
- persists identity governance with the versioned template snapshot;
- never creates `ImportBatch`, `IngestionRecord` or `QuarantineRecord` rows;
- never writes source facts or the star schema;
- never invokes Business Rules, matching, `EmployeeService` or canonical promotion;
- never changes FileWatchService, active adapters, result contracts or `BEFORE` semantics.

## 6. Integration boundary with the future engine

The draft contract is a validation target for the future agnostic engine. It is
not passed to `IngestionBatchService`, `IngestionOrchestrator` or any source
adapter. Employee/canonical mapping is deliberately not part of this screen;
the Employee Engine will own that later. Identity governance is declared here,
but the future Identity Resolver/Employee Engine will execute it only after
facts are committed. The current persisted snapshots are library records only;
a runtime registry and batch-pinned policy snapshots remain future work.

## 7. Files

- `iam_automation/application/ingestion/configuration_contracts.py`
- `iam_automation/application/ingestion/configuration_service.py`
- `iam_automation/application/ingestion/template_repository.py`
- `iam_automation/templates/admin/ingestion_template_library.html`
- `iam_automation/interfaces/web/ingestion_configuration_routes.py`
- `iam_automation/templates/admin/ingestion_source_configuration.html`
- `iam_automation/static/css/app.css`
- `iam_automation/templates/base.html`
- `iam_automation/webapp.py`
- `tests/test_ingestion_configuration.py`

## 8. Current limitations and open questions

- Sample bytes remain in memory for a short time; saved definitions remain in SQLite.
- Approval validates the current draft contract and freezes a version, but does not publish or activate it.
- Only the first validation row is currently rendered by the prototype; the
  contract supports multiple rows for the next UI iteration.
- Preview typing and validation intentionally cover the first safe subset, not a
  complete ETL transform system.
- Approval authority is limited to application and master administrators; the
  operational publication authority remains undecided.
- The future definition version must be pinned to a batch before production
  configuration can be activated.
