# Configuration UI Design

**Status:** Prototype implemented as an isolated draft laboratory

**Date:** 2026-09-22

**Related architecture:** [Ingestion Engine Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)

## 1. Purpose

This prototype validates the future source-configuration workflow before any
production ingestion lifecycle is changed. It lets an administrator describe a
source schema, choose imported columns, configure inferred data types and
structural validation expectations, declare the source's identity authority,
then test a bounded sample in memory.

The page is intentionally a DRAFT-only design laboratory. It does not create a
production `SourceDefinition`, activate a watcher or invoke the existing
orchestrator.

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
- **DECLARE IDENTITY AUTHORITY:** choose whether the template is an Identity
  Seed, Identity Enrichment or Evidence Only. For each included source field,
  the administrator can explicitly allow matching, classify it as Strong or
  Supporting, and allow identity creation only for strong identifiers. This is
  source governance, not Employee/canonical field mapping.
- **CHECK DRAFT:** run structural checks and a normalized preview in memory.

The interaction is server-rendered with HTMX partial swaps and retains normal
form actions as a full-page fallback. This keeps the screen approachable for
Business Rules users while preserving explicit loading, error and empty states.

Advanced source identity, reader hints, validation constraints and drift severity
remain available in a disclosure after the guided flow; they are not the first
thing a user must understand.

The page offers only draft-oriented actions such as `Keep draft in this session`
and `Preview selected data`. There is no Activate, Publish, Enable watcher or Run
ingestion action.

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

The contract is frozen and serializable to a Flask session. `status` is always
`DRAFT`; it is not the future persisted `SourceDefinition` contract.

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

The prototype:

- stores drafts only in the signed Flask session;
- does not use the governed employee-field catalog for source selection;
- captures identity governance only in the signed browser session;
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
facts are committed. A later phase may introduce persisted immutable
definitions, policy snapshots and a registry only after this workflow is
accepted.

## 7. Files

- `iam_automation/application/ingestion/configuration_contracts.py`
- `iam_automation/application/ingestion/configuration_service.py`
- `iam_automation/interfaces/web/ingestion_configuration_routes.py`
- `iam_automation/templates/admin/ingestion_source_configuration.html`
- `iam_automation/static/css/app.css`
- `iam_automation/templates/base.html`
- `iam_automation/webapp.py`
- `tests/test_ingestion_configuration.py`

## 8. Current limitations and open questions

- Drafts are browser-session scoped and disappear when the session is reset.
- Only the first validation row is currently rendered by the prototype; the
  contract supports multiple rows for the next UI iteration.
- Preview typing and validation intentionally cover the first safe subset, not a
  complete ETL transform system.
- The team still needs to decide whether drafts later move to a local file,
  dedicated draft persistence or an approved configuration publication workflow.
- The future definition version must be pinned to a batch before production
  configuration can be activated.
