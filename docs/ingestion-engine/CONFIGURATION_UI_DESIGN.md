# Configuration UI Design

**Status:** Persisted template library with identity cards and ingestion ordering; runtime activation remains out of scope

**Date:** 2026-09-24

**Related architecture:** [Ingestion Engine Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)

## 1. Purpose

This prototype validates the future source-configuration workflow before any
production ingestion lifecycle is changed. It lets an administrator describe a
source schema, choose imported columns, configure inferred data types and
structural validation expectations, then test a bounded sample in memory.
Identity authority is configured from the saved template library.

The page saves versioned draft snapshots in SQLite and offers a separate
template library for continuing configuration and approval. These records are
configuration evidence only: they do not activate a watcher or invoke the
existing orchestrator.

## 2. User workflow

```text
READ FILE -> REVIEW RAW STRUCTURE -> COMPOSE HEADERS -> REVIEW DATA -> SELECT COLUMNS -> CHECK DRAFT -> CONFIGURE TEMPLATE IDENTITY AND ORDER IN LIBRARY
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
  value unchanged. Columns appear as a vertical accordion list. Each closed row
  shows inclusion, source name, template key, selected cleanup, type and position;
  field settings expand one at a time. Cleanup remains editable inside the expanded
  settings, while its selected value updates in the closed-row summary. The
  included-field count follows checkbox changes.
- **CHECK DRAFT:** run structural checks and a normalized preview in memory.
- **CONFIGURE IN THE LIBRARY:** each saved source appears as a card. A modal
  lets the administrator choose whether the report may introduce employees,
  find existing employees, or remain evidence only, then select identifier
  fields from that template and set its maximum matching-field count. Identifier
  values stay strings. New and older templates start with a limit of three until
  changed in the modal. A report that may
  propose new Employee UUIDs needs at least two distinct included Strong IDs,
  both selected for matching and explicitly authorized for creation. Approved
  definitions start a new draft when identity settings change.
- **SET INGESTION ORDER:** move template cards earlier or later. The order is
  stored by stable source key in separate metadata, so changing order does not
  rewrite immutable approved definition versions.
- **DELETE REPORT TEMPLATE:** an administrator confirms removal from the active
  library. The template is excluded from the active order and new Employee field
  choices; its version snapshots, attribution and existing Employee-template
  references remain preserved as evidence. Recreating a report with the same
  internal key restores it as a new draft version and records the restoration.
- **CONFIGURE TEMPLATE BEHAVIOR:** an HTMX modal on each card can select or
  create a watched subfolder strictly below the configured SharePoint root,
  choose the active Business Rules calendar time zone or a custom IANA time
  zone, and select date/time fields for future conversion. If no saved default
  calendar context exists, the card shows a warning. A date-field skip rule can
  also be saved by choosing a comparison and a calendar date. Folder paths, calendar
  references, timezone choices and skip rules are configuration metadata only;
  they do not activate the watcher, convert values or exclude rows.
- **CONFIGURE TEMPLATE OBJECT:** a separate card lets the user name an object,
  select saved report templates as sources, and automatically builds its
  properties from their included fields. The user selects Strong and Supporting
  identifiers declared by those report templates, then creates match groups:
  one selected Strong identifier from an anchor report can link to one or more
  Strong identifiers from other reports. A source graph must connect every
  selected report. Saved relationship groups expand to the existing persisted
  pair list so earlier object-template versions remain readable. Each saved
  version retains source lineage and owner/editor attribution.

The interaction is server-rendered with HTMX partial swaps and retains normal
form actions as a full-page fallback. This keeps the screen approachable for
Business Rules users while preserving explicit loading, error and empty states.

Reader hints, validation constraints and drift severity remain available in a
disclosure after the guided flow; they are not the first thing a user must
understand.

The template library shows one card per source with version history, creator and
last editor attribution. Administrators can configure identity, reorder templates,
continue a draft, approve a valid draft, or create a new draft from an approved
version. Approved versions are immutable.
There is no Activate, Publish, Enable watcher or Run ingestion action.

## 3. Parallel runtime and deprecation register

The new template library and the production ingestion path are parallel systems
for now. Report and Template Object versions are configuration evidence only.
They do not replace the current source-specific adapters, the hard-coded runtime
dispatcher, canonical Employee matching, or approval/application workflows.

Legacy entry points carry source-level `DEPRECATED` notes to preserve the
migration trail. The marker means “planned replacement, still active”; it does
not remove or redirect callers. Keep each compatibility path until its runtime
replacement exists and source-specific parity is demonstrated.

| Legacy entry point | Replacement target | Current status |
|---|---|---|
| `IngestionOrchestrator` hard-coded factory dispatch | Future `SourceRecognizer` + `SourceRegistry` | Active dispatcher; no runtime registry is wired yet. |
| Master Roster, AccessNow and RSR hand-written batch persistence | `IngestionBatchService` | Still active per source; Roster Lock already delegates to the generic batch service. |
| `find_worker_matches` and source-specific matching calls | Future runtime resolver consuming Template Object relationships | Still active for the existing Employee model; the Template Object only stores configuration. |
| `DraftFieldMapping` and `template_mappings` | Draft field keys/cleanup plus versioned report-template snapshots | Legacy configuration compatibility is retained; new library editing does not write the legacy mapping table. |

Do not treat existing matching or application workflows as switched or
inactive: the new object configuration is not consumed by runtime ingestion.
No adapter, canonical Employee flow or old mapping table is deleted by this
phase.

## 4. Draft contract

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

## 5. Validation and preview behavior

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

## 6. Isolation guarantees

The configuration library:

- stores draft and approved template snapshots in an additive SQLite table;
- stores source-template execution order in a separate additive table;
- stores removal/restoration events in `source_template_lifecycle_events` and
  retains all report version rows and source lineage;
- stores the user-named Template Object as versioned configuration in the
  existing `employee_template_versions` history table; selected identifiers,
  cross-report Strong links and generated property references retain their
  source-report lineage;
- keeps the current editing pointer in the signed Flask session;
- records the actor and timestamps for creation, edits and approval;
- preserves approved versions and starts a new version when further configuration is needed;
- derives object properties from included fields in selected saved report
  templates and does not mutate the governed field catalog;
- persists identity governance with the versioned template snapshot;
- persists the selected SharePoint subfolder, the pinned calendar/timezone
  settings, selected date/time fields and future date-age skip rules with the
  template snapshot;
- edits identity settings only through the template library; source-column editing
  remains focused on inclusion, field keys, data types and cleanup;
- never creates `ImportBatch`, `IngestionRecord` or `QuarantineRecord` rows;
- never writes source facts or the star schema;
- reads the saved Business Rules calendar configuration only; it never executes
  the Rules Engine, matching, `EmployeeService` or canonical promotion;
- does not execute saved time conversion or row skip policies;
- validates created or selected watcher paths remain below the configured
  SharePoint root, and does not connect them to the production watcher;
- never changes FileWatchService, active adapters, result contracts or `BEFORE` semantics.

## 7. Integration boundary with the future engine

The report draft contract is a validation target for the future agnostic engine.
It is not passed to `IngestionBatchService`, `IngestionOrchestrator` or any source
adapter. The Template Object stores a user-chosen object name, source property
references, selected identifiers and Strong links across reports. This phase only
records configuration: it does not create objects, match identities, define
merge precedence or map differently named fields into shared canonical
attributes. Those decisions remain with a future object engine. Identity
governance is declared in report templates, but a future resolver will execute it
only after facts are committed. These snapshots are library records only; a
runtime registry and batch-pinned policy snapshots remain future work.

## 8. Files

- `iam_automation/application/ingestion/configuration_contracts.py`
- `iam_automation/application/ingestion/configuration_service.py`
- `iam_automation/application/ingestion/template_repository.py`
- `iam_automation/application/ingestion/object_template_repository.py`
- `iam_automation/database/alembic/versions/0025_employee_template_versions.py`
- `iam_automation/database/alembic/versions/0026_source_template_deletions.py`
- `iam_automation/database/alembic/versions/0027_source_template_lifecycle_events.py`
- `iam_automation/application/ingestion/object_template_repository.py`
- `iam_automation/templates/admin/ingestion_template_library.html`
- `iam_automation/templates/admin/_object_template_card.html`
- `iam_automation/templates/admin/_object_template_modal.html`
- `iam_automation/templates/admin/_object_template_match_row.html`
- `iam_automation/templates/admin/_ingestion_delete_template_modal.html`
- `iam_automation/templates/admin/_ingestion_template_cards.html`
- `iam_automation/templates/admin/_ingestion_template_behavior_modal.html`
- `iam_automation/static/js/ingestion-template-library.js`
- `iam_automation/interfaces/web/ingestion_configuration_routes.py`
- `iam_automation/templates/admin/ingestion_source_configuration.html`
- `iam_automation/static/css/app.css`
- `iam_automation/templates/base.html`
- `iam_automation/webapp.py`
- `tests/test_ingestion_configuration.py`

## 9. Current limitations and open questions

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
