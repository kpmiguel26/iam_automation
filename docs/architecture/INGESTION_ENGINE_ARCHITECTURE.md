# Ingestion Engine Architecture

**Status:** Design baseline; configuration UI prototype implemented as an isolated draft laboratory

**Date:** 2026-09-22

**Scope:** Source-agnostic ingestion for the existing local, read-only IAM Automation application.

**Implementation-order note (2026-09-22):** The approved sequence now validates
the future `SourceDefinition` contract through an isolated READ/STRUCTURE/
MAPPING/CHECK configuration prototype before modifying the production ingestion
lifecycle. The prototype is documented in
[CONFIGURATION_UI_DESIGN.md](../ingestion-engine/CONFIGURATION_UI_DESIGN.md).
Production batch extraction, persisted definitions and source migration remain
gated phases.

This document defines the boundary for a future Ingestion Engine. It is based on
the current implementation on `fix/sqlite-relational-rule-evaluation` and is
intentionally incremental. It does not authorize a production rewrite, a new
distributed platform, or a change to the Phase One read-only boundary.

## 1. Purpose

The Ingestion Engine will convert an external artifact into trustworthy internal
evidence:

```text
unpredictable artifact
        -> recognized source
        -> parsed and normalized records
        -> structurally validated records
        -> governed canonical fields
        -> staged evidence and source facts
        -> completed import batch
```

The engine is an application-layer orchestrator. It coordinates readers,
parsers, normalizers, validators, mappers, persistence and batch lifecycle, but
does not own business policy or canonical employee truth.

## 2. Current state

### Current flow

The watcher is discovery-only. `FileWatchService.scan_once` discovers files,
updates the watcher manifest and creates local notifications; the explicit
Source Updates action performs ingestion. This preserves the current rule that a
watcher scan does not populate SQLite with source rows.

```text
watcher scan
    -> FileObservation / manifest / notification
    -> administrator selects Source Updates import
    -> IngestionOrchestrator
    -> hard-coded source factory
    -> source application service or public adapter facade
    -> source reader
    -> source normalizer / merger
    -> source validator
    -> ImportBatch(PROCESSING)
    -> IngestionRecord / QuarantineRecord
    -> StarSchemaWriter source facts
    -> ImportBatch(COMPLETED or COMPLETED_WITH_WARNINGS)
    -> commit
    -> legacy JSON cleanup
    -> BEFORE rules against the committed batch
    -> AFTER rules and advisory findings
    -> optional explicit approved canonical promotion
```

The current orchestrator calls the adapter first and evaluates rules after a
batch identifier has been returned. Therefore the implemented meaning of
`BEFORE` is “before AFTER evaluation, while evidence is still in the staged
ingestion model”, not “before the adapter reads or persists anything”. A true
pre-adapter phase would require a candidate-record contract and stable
correlation keys before `IngestionRecord` persistence; that is a separate
decision, not an implicit consequence of the current enum value.

### Current responsibilities

| Component | Current responsibility | Boundary concern |
|---|---|---|
| `FileWatchService` | Filesystem discovery, manifest and notifications | Correctly does not ingest source rows; source recognition remains partly hard-coded in discovery metadata. |
| `employee_routes.py` | Explicit import command and UI workflow | Knows source names and special-cases AccessNow folder ingestion. |
| `IngestionOrchestrator` | Source dispatch plus `BEFORE`/`AFTER` rule coordination | Factory map is hard-coded; result contract is structural rather than a generic batch hand-off. |
| Roster Lock service | Read, normalize, validate, deduplicate, create batch, stage records, write facts and complete batch | Owns most generic lifecycle work and source-specific behavior together. |
| Master Roster service | Same lifecycle plus Master Roster-specific reader/normalizer/validator | Duplicates batch and fact persistence flow. |
| AccessNow service | Read multiple files, merge active/termination views, validate, stage, match, write facts and complete batch | Combines multi-file source policy, matching and persistence. |
| RSR public adapter | Read, normalize, validate, stage, write facts, complete batch and later match rows | The public adapter still owns database persistence and matching compatibility paths. |
| `StarSchemaWriter` | Writes generic snapshot/field facts, source-specific typed facts and reconstructs payloads | Infrastructure writer also discovers new fields and mappings during ingestion. |
| `EmployeeService` | Explicit matching, canonical worker promotion, lineage and history | Correctly remains outside the future generic ingestion core. |
| Rules Engine | Consumes `IngestionBatch` evidence, evaluates advisory rules and writes findings | The generic contract is reconstructed from persistence rather than produced directly by ingestion. |

### Existing contracts that are reusable

The repository already has a useful foundation:

- `IngestionBatch`, `NormalizedRecord`, `FieldMapping`, `BatchMetadata` and
  `RecordMetadata` in `application/ingestion/contracts.py`.
- `EvidenceRepository.batch_for_id`, which gives the Rules Engine a
  source-neutral read boundary.
- `RuleContext`, `RuleResult` and `RulePhase` in `application/rules/base.py`.
- `RuleResult` JSON-like detail validation, which prevents adapter objects and
  paths from crossing the Rules Engine boundary.
- `RuleCatalogRepository` and the governed `dim_source`, `dim_field` and
  `source_field_mapping` tables.
- Existing deduplication helpers and the source-row uniqueness constraint.

The main limitation is that the ingestion adapters do not yet produce an
`IngestionBatch` as their primary output. The current `SqliteEvidenceRepository`
materializes that contract after persistence.

## 3. Target architecture

```text
External artifact
      |
      v
File Watcher / explicit import command
      |
      v
FileDetected DTO
      |
      v
SourceRecognizer ------------------------------+
      |                                         |
      v                                         |
SourceRegistry -> SourceDefinition             |
      |                                         |
      +-----------------------------------------+
      v
Ingestion Engine
      |
      +--> Reader
      +--> Parser
      +--> Normalizer
      +--> Structural Validator
      +--> Canonical Mapper
      +--> Deduplication policy
      +--> IngestionBatchService
                   |
                   +--> generic staging
                   +--> source facts / governed field facts
                   +--> batch completion
      |
      v
Committed IngestionBatch / source evidence
      |
      +--> BEFORE rules (advisory, post-staging)
      +--> AFTER rules (advisory, post-import)
      +--> reconciliation / matching
      +--> optional approved canonical promotion
```

The engine must not contain branches such as `if source == "ROSTER_LOCK"` for
source meaning. Source-specific implementations may exist behind ports selected
by a `SourceDefinition`, but the orchestration and lifecycle code must remain
generic.

The first target is not a fully dynamic ETL platform. It is a small modular
monolith that supports the current Excel/CSV sources and can add a source
without duplicating batch lifecycle code.

## 4. Proposed responsibilities

### Watcher

- Detect filesystem artifacts and stable signatures.
- Maintain the existing manifest and local notification behavior.
- Emit or provide a `FileDetected` command/DTO.
- Never parse, normalize, write source rows or evaluate business rules.

### SourceRecognizer

- Deterministically compare filename, extension, sheet names and headers with
  registered source signatures.
- Return a source candidate, diagnostics and a confidence/status value.
- Never use ML or arbitrary user code.
- Allow an explicit user-selected source to override recognition only with an
  auditable reason when the UI supports that flow.

### SourceRegistry

- Resolve an active source identity and definition version.
- Provide definitions to the engine without exposing storage details.
- Reject ambiguous or inactive definitions before batch creation.

### SourceDefinition

- Describe source metadata, reader settings, schema, mappings, transforms,
  validations, drift policy and ingestion policy.
- Be data, not executable Python.
- Be immutable for one ingestion run.

### Reader

- Open the supported artifact format and expose raw rows/sheets with source
  location metadata.
- Own no database session and no business policy.

### Header interpretation and multiline headers

Header interpretation is an explicit configuration step, not an assumption that
the first non-empty row is the schema. The configuration UI must expose a bounded
raw grid with sheet, row number and column position so an administrator can select:

- one primary header row for ordinary tabular files;
- multiple header/context rows when a source uses hierarchical labels; or
- no header row when the artifact has positional columns only.

Selected header rows are composed per column by retaining non-empty values in
source order. Empty cells in the selected rows do not create separators. The raw
composite name and the administrator's draft field key are both retained. For
example, the Master Roster fixture contains `NUID`/`LogonID` and
`NPN`/`LogonID` in the same header region; these must remain separate source
fields such as `nuid` and `npn`, not be merged into one `logon_id` value.

The UI may recommend a header range using explainable signals such as the widest
text-like row and populated context above duplicate labels, but the user can
change the selection. Duplicate or ambiguous resulting names must be visible and
editable before mapping. Header composition is parsing/configuration behavior;
it does not perform matching or canonical employee promotion.

### Parser

- Convert a reader output into a stable row representation.
- Preserve source row number, sheet and raw header identity needed for evidence.
- Report batch-level format failures separately from row-level parse issues.

### Normalizer

- Apply only registered transformations.
- Produce typed or explicitly string-preserving values with source lineage.
- Keep identifiers such as `001234` as strings.

### Structural Validator

- Validate required headers, types, nullability, row shape, duplicate source keys
  and source-level constraints.
- Return typed record issues rather than raising for every bad row.
- Distinguish record-level invalidity from a batch-level artifact failure.

### Canonical Mapper

- Map external columns to governed canonical field IDs/keys.
- Preserve original source field key and mapping version for lineage.
- Never infer canonical employee truth; it only creates normalized source
  evidence.

### IngestionBatchService

This is the recommended name for the application-facing service. It should own
the lifecycle of one ingestion batch and expose a narrow unit-of-work boundary:

- start a batch with source identity and definition version;
- record source metadata and counts;
- persist valid staged records and row-level quarantine issues;
- invoke the governed fact writer;
- mark `COMPLETED`, `COMPLETED_WITH_WARNINGS` or `FAILED`;
- make retry and idempotency decisions explicit;
- publish a typed `StageOutcome` after commit.

`BatchLifecycleService` remains a reasonable internal component name if the
implementation separates lifecycle state transitions from the ingestion facade.
The repository should not create both as independent public services without a
real responsibility split.

### Staging repository

- Persist `ImportBatch`, `IngestionRecord` and ingestion quarantine evidence.
- Keep source evidence append-only.
- Use the existing ORM/session conventions.
- Avoid deciding canonical employee status or writing authoritative systems.

### Fact persistence

- Persist source snapshots and governed field facts after structural validation.
- Keep source-specific typed facts isolated behind a writer port.
- Keep `StarSchemaWriter` as an infrastructure implementation during migration.

### Matching and canonical promotion

Matching may consume staged facts and produce candidate links or discrepancies,
but it should remain an application reconciliation service, not a hidden side
effect of generic parsing. Approved canonical promotion remains outside the
Ingestion Engine and retains its current explicit review/authorization boundary.

### Rules integration

- Rules execute only after the staged batch is committed and addressable.
- `BEFORE` remains advisory and post-staging unless a future candidate-record
  phase is explicitly approved.
- `AFTER` runs after import completion.
- Rule findings must never roll back or block a successful import in Phase One.

## 5. SourceDefinition

The conceptual model should be typed at runtime:

```text
SourceDefinition
  id: SourceId
  name: str
  version: int
  active: bool
  watcher: WatcherSettings
  recognition: RecognitionSettings
  reader: ReaderSettings
  fields: tuple[FieldDefinition, ...]
  mappings: tuple[FieldMappingDefinition, ...]
  transformations: tuple[TransformStep, ...]
  validations: tuple[ValidationDefinition, ...]
  schema_drift_policy: SchemaDriftPolicy
  ingestion_policy: IngestionPolicy
  identity_governance: IdentityGovernancePolicy
```

### Identity governance belongs to the template

The source template is not only a reader description. It is also the declared
authority of that source over identity. This policy is captured alongside the
source schema so the future Employee Engine does not have to infer authority
from a filename, a field label or an adapter implementation.

The draft shape is intentionally explicit:

```yaml
identity_governance:
  role: IDENTITY_SEED # IDENTITY_ENRICHMENT | EVIDENCE_ONLY
  can_create_employee: true
  identifiers:
    - field_key: employee_number
      strength: STRONG
      can_match: true
      can_create_identity: true
    - field_key: nuid
      strength: STRONG
      can_match: true
      can_create_identity: true
    - field_key: user_principal_name
      strength: SUPPORTING
      can_match: true
      can_create_identity: false
    - field_key: employee_name
      strength: SUPPORTING
      can_match: false
      can_create_identity: false
```

The `field_key` points to the user-approved source-schema key while the raw
composed header remains available for evidence. This is important for the
Master Roster case: `CLIENT · Kaiser Systems · NUID · LogonID` may be named
`nuid`, and `OPERATIONS · Healthcare Systems · NPN · LogonID` may be named
`npn`, without losing their distinct raw origins.

The policy has these guardrails:

- `IDENTITY_SEED` may allow creation, but only through explicitly selected
  `STRONG` identifiers.
- `IDENTITY_ENRICHMENT` may contribute matching evidence but cannot create an
  Employee UUID.
- `EVIDENCE_ONLY` cannot match or create identity; its facts remain available
  for audit and analysis.
- A template may nominate at most three source fields for identity matching.
  The laboratory enforces this limit in the UI and in server-side validation.
- `SUPPORTING` fields such as names, email addresses and dates may explain or
  strengthen a future match, but can never create identity alone.
- The policy is versioned with the template and snapshotted with a future
  batch/fact lineage record so later template edits cannot reinterpret history.

The execution boundary remains deliberate:

```text
Fact row
   -> template identity policy
   -> future Identity Resolver / Employee Engine
   -> existing match: link fact to Employee UUID
   -> no match + create authority: propose/create according to that stage's approval rules
   -> no match + no authority: unresolved evidence
```

The generic Ingestion Engine only stages and commits source evidence. It does
not invoke matching as part of its generic lifecycle. Declaring authority in a
template therefore does not pull matching into Phase One; it gives the later
identity stage a governed contract to consume.

The initial runtime representation should use frozen dataclasses, matching the
repository's existing contract style. The definition must be immutable once an
ingestion run starts.

### Persistence recommendation

Use a hybrid model:

1. typed in-memory dataclasses at the engine boundary;
2. versioned SQLite configuration for active definitions and governance;
3. a `SourceRegistry` interface that hides whether a definition came from
   SQLite, a test fixture or a future import/export file.

SQLite is preferred over JSON-only configuration because this application already
uses local SQLite as its governed runtime snapshot, has versioned catalog tables,
and needs auditability and controlled publication. JSON may remain an import/export
format, not the runtime source of truth.

No new SourceDefinition tables are created by the current configuration
laboratory. The current `dim_source`, `dim_field` and `source_field_mapping`
tables remain reusable for the source-field catalog, but identity governance is
definition-level policy rather than an employee-field mapping. A later
publication phase must persist immutable definition versions, the identity
policy, reader settings and the physical fact-table contract together. Saving a
browser draft must never create a fact table or activate a watcher.

## 6. Canonical mapping

External field names must stop at the ingestion boundary:

```text
Roster Lock:  "Employee ID"
Fieldglass:   "Worker ID"
AccessNow:    "UserIdentifier"
                     |
                     v
              canonical source field: employee_id
```

The mapping must retain both sides:

```text
source_field_key = "Worker ID"
field_id         = governed employee_id field
field_key        = "employee_id"
mapping_version  = 3
transform        = normalize_id
```

For a multiline source, `source_field_key` retains the composed raw identity
needed for evidence while `field_key` is the user-approved draft name. Distinct
identifiers that share a display suffix, such as `NUID · LogonID` and
`NPN · LogonID`, must not map to the same target key unless a later, explicit
source-specific normalization contract defines that operation.

This does not mean every source identifier is the same business identity. The
canonical field vocabulary describes the value's meaning; identity resolution
still uses source-scoped identifier types and the existing identity rules.

Historical rules and findings already use source-specific field keys. They must
remain readable. New rules should resolve governed field IDs/keys through the
catalog, and a later migration may add aliases without rewriting historical JSON.

## 7. Type system

The initial supported types should be:

- `string`
- `integer`
- `decimal`
- `boolean`
- `date`
- `datetime`
- `enum`

Every field definition should declare `nullable`, `required`, normalization and
whether it is an identifier. Required is a structural ingestion property;
nullable is a value-level property. An empty string should not silently become a
valid identifier.

Identifiers remain strings even when they look numeric. For example:

```text
"001234" -> "001234"
```

Numeric conversion must never remove leading zeroes from employee IDs, NUIDs,
NPNs, worker IDs, work orders or other governed identifiers.

## 8. Transform registry

Transforms are named, allow-listed operations resolved by a registry:

```text
trim
lower
upper
parse_date
map_values
normalize_email
normalize_id
coalesce
regex_extract
replace
```

Configuration stores the transform name and typed parameters. It never stores or
executes Python source, import paths or arbitrary callables. A transform failure
becomes a typed record issue or batch error according to the operation's contract.

## 9. Validation boundary

### Ingestion validation

Ingestion validation answers whether the artifact can be safely represented as
source evidence:

- required header is present;
- value parses as a date or number;
- required field is not null/empty;
- source identifier has an acceptable shape;
- duplicate source key is detected;
- row has the expected structural shape.

These issues belong to `QuarantineRecord`/batch outcome and may make a batch
`COMPLETED_WITH_WARNINGS` or `FAILED` according to the source definition.

### Business Rules

Business Rules answer whether valid evidence deserves operational review:

- terminated employee still has active access;
- a worker is absent from an expected system;
- statuses across sources are inconsistent;
- a rehire interval is inside a configured range.

These create advisory `RuleFinding` and `FactQuarantine` projections. They do not
reject or undo the import in Phase One.

## 10. Schema drift

The future drift detector should compare observed headers and inferred/declared
types with the active `SourceDefinition` version:

| Drift | Proposed outcome |
|---|---|
| New optional column | `INFO` or `WARNING`; preserve if mapping is unknown. |
| Missing optional column | `WARNING`; continue with null evidence. |
| Missing required column | `BLOCKING` structural batch issue. |
| Renamed column with known alias | `INFO`; record the alias used. |
| Renamed column without alias | `WARNING` or `BLOCKING` depending on field requirement. |
| Incompatible type change | `WARNING` for row-level failures or `BLOCKING` if the batch cannot be trusted. |

`BLOCKING` here means the ingestion batch cannot be safely staged as valid
evidence. It does not mean a business-rule match blocks an import or causes an
authoritative write.

Full schema-drift automation is not part of the first implementation slice.

## 11. Source recognition

Recognition should be deterministic and explainable. Initial signals are:

- filename pattern;
- file extension;
- sheet name;
- required headers;
- optional headers;
- configured watched directory.

The recognizer should return a diagnostic value such as:

```text
RecognitionResult
  source_id: str | None
  definition_version: int | None
  matched_signals: tuple[str, ...]
  rejected_signals: tuple[str, ...]
  status: UNIQUE | AMBIGUOUS | UNKNOWN
```

Recognition must not guess silently when two active definitions match. The UI can
ask for an explicit source selection and preserve that selection in the import
audit record.

## 12. Versioning

`SourceDefinition` versions should be immutable. An ingestion batch must
eventually retain:

```text
source_id
source_definition_version
mapping_version(s)
transform configuration snapshot
```

This is required to explain why the same artifact produced different normalized
values after a configuration change. The current `ImportBatchModel` does not yet
have a definition-version field; adding it belongs to a later additive migration,
not to the documentation-only phase.

## 13. Batch lifecycle

The current code is suitable for extraction into an `IngestionBatchService`, but
the extraction must preserve the existing `ImportBatch` table and public result
dataclasses.

Recommended lifecycle:

```text
NEW
  -> PROCESSING
  -> COMPLETED
  -> COMPLETED_WITH_WARNINGS
  -> FAILED
```

The stored status vocabulary should be verified against all existing consumers
before adding states. Record statuses remain separate from batch status:

```text
STAGED | QUARANTINED | MATCHED | CURRENT | APPLIED
```

The service should own:

- batch start and source metadata;
- count accumulation;
- row-level issue recording;
- generic deduplication coordination;
- fact writer invocation;
- completion/failure marker;
- definition-version attachment when available;
- typed post-commit outcome.

The service should not own canonical employee promotion, source-specific identity
policy or business-rule evaluation.

## 14. Ingestion metrics

The first typed outcome can carry only metrics already available or cheap to
compute:

```text
rows_read
rows_staged
rows_quarantined
duplicate_count
parse_failures
null_required_fields
schema_drift_detected
```

Do not introduce a telemetry platform. Persist batch counts using existing
`ImportBatch` columns where possible; keep richer diagnostics in structured local
audit/evidence only when needed for review.

## 15. Error model

The engine should distinguish categories without requiring a new hierarchy for
every source:

```text
ReaderError
ParserError
NormalizationError
MappingError
StructuralValidationError
PersistenceError
BatchLifecycleError
```

Record-level errors become typed issues attached to a source row and may allow
the rest of the batch to continue. Batch-level errors mean the artifact cannot be
trusted as a coherent batch and should mark the batch failed or leave it in a
recoverable processing state.

Business-rule evaluator errors remain advisory and are captured as rule results;
they must not convert a committed import into a failed import.

## 16. Transaction boundaries

The current SQLAlchemy behavior supports these boundaries:

1. File reading, parsing and normalization occur outside a database transaction.
2. One batch transaction creates `ImportBatch`, valid/quarantined records,
   source facts and counters.
3. The batch is committed before rules run.
4. Rule findings are persisted in a separate transaction and cannot roll back
   source evidence.
5. Legacy JSON cleanup currently occurs after the fact transaction. The future
   lifecycle service should make that cleanup idempotent and observable, or move
   it into a safe atomic unit after every consumer is relational.
6. Canonical promotion remains a separate explicit transaction owned by the
   employee/reconciliation workflow.

The first extraction must not widen a transaction to include file I/O, rules,
notifications or canonical promotion.

## 17. Migration strategy

Use a strangler migration rather than rewriting all adapters:

1. Freeze current behavior with focused contract and parity tests.
2. Extract batch lifecycle and persistence coordination.
3. Introduce typed `SourceDefinition` and `SourceRegistry` ports.
4. Adapt one source to return a generic candidate/staging input.
5. Run old and new paths against the same fixture and compare counts, lineage,
   source facts, statuses and deduplication.
6. Migrate additional sources incrementally.
7. Add persisted definitions and configuration UI only after the runtime path is
   stable.

Roster Lock is the recommended pilot because its current flow is comparatively
linear: one XLSX file, one reader/normalizer/validator path, no multi-file
merge, and no matching side effect during ingestion. This is a recommendation,
not an authorization to change it yet.

## 18. Non-goals

The design does not include:

- a visual DAG editor;
- distributed workers or a queue platform;
- arbitrary Python transforms;
- ML source detection;
- a generic workflow/ETL framework;
- new authoritative write-back behavior;
- a major database redesign;
- unrelated new adapters;
    - a production activation/publishing UI;
- automatic canonical employee promotion;
- making business-rule findings blocking.

## 19. Configuration UI boundary

The isolated prototype is organized as:

```text
READ FILE -> STRUCTURE -> HEADER COMPOSITION -> MAPPING -> CHECK
```

Conceptual flow:

1. Read a bounded CSV/XLSX sample without connecting the watcher.
2. Show a raw worksheet grid and allow one or more header/context rows.
3. Compose multiline headers per column and allow draft field-key edits.
4. Describe a DRAFT source definition in the browser session.
5. Review suggested field types while preserving identifiers as strings.
6. Select source columns, accept or override inferred data types and configure
   source-level transforms.
7. Defer employee/canonical field mapping to the future Employee Engine.
8. Configure required/optional fields and structural validations.
9. Test against a sample artifact and review diagnostics without staging.

The future production UI may add publication and activation after persisted
definition versioning and authorization are approved.

This UI must remain a local governance tool. It must not expose arbitrary SQL,
Python or physical database schema editing.

## 20. Open questions

1. What is the canonical field vocabulary for identifiers that are source-scoped
   and not interchangeable, such as employee number, vendor employee ID and RSR
   worker ID?
2. `BEFORE` is approved as post-staging/pre-`AFTER`; a true pre-adapter phase is
   explicitly out of scope for this implementation order.
3. Structurally `QUARANTINED` rows remain auditable but are excluded from normal
   Business Rules evaluation in this phase.
4. Matching and reconciliation remain outside the generic engine; the engine
   must not invoke matching as part of its generic lifecycle.
5. Where should the immutable definition-version snapshot be stored in the
   current SQLite publication model?
6. How should AccessNow's active/termination multi-file merge be represented in a
   generic definition without hiding important source policy?
7. Which type changes are warnings and which are batch-blocking for each current
   source?
8. Does the current separate legacy JSON cleanup need a repair marker before the
   lifecycle extraction is considered complete?

## 21. Revised implementation order

The first slice is now a non-production configuration prototype. It validates the
future contract, including multiline header composition, before any production
lifecycle extraction:

```text
READ FILE -> STRUCTURE -> HEADER COMPOSITION -> MAPPING -> CHECK
```

See [CONFIGURATION_UI_DESIGN.md](../ingestion-engine/CONFIGURATION_UI_DESIGN.md)
for the implemented boundary. The production lifecycle slice remains gated:

### Configuration prototype files

- Add typed draft contracts under `iam_automation/application/ingestion/`.
- Add an isolated configuration service and administrative blueprint.
- Use session-backed DRAFT state and read-only `dim_field` catalog access.
- Inspect bounded CSV/XLSX samples without creating ingestion records.

### Later production lifecycle files

- Add `iam_automation/application/ingestion/batch_service.py` with the generic
  batch lifecycle/application boundary.
- Extend `iam_automation/application/ingestion/contracts.py` with typed outcome
  and issue values only as required by the service.
- Keep `iam_automation/application/ingestion/orchestrator.py` as the compatibility
  entry point, but have it call the lifecycle service.
- Refactor `iam_automation/application/roster_lock_ingestion_service.py` into a
  thin compatibility facade over the pilot path.
- Leave `source_adapters/roster_lock/` responsible for reading, normalization
  and source validation during the first slice.

### Required tests

- batch counts and completion status remain identical;
- row-level structural quarantine remains identical;
- source-row deduplication remains identical;
- star-schema facts and lineage remain identical;
- retry after a partial/duplicate observation remains safe;
- rules still run only after commit;
- a failing rule never changes the committed import result;
- existing public `ingest_file` result shape remains compatible;
- no canonical employee is created by the ingestion path.

### Explicitly deferred until the prototype is accepted

- SourceDefinition persistence tables;
- SourceRegistry database implementation;
- generic recognition for every source;
- migration of AccessNow and RSR;
- schema-drift automation;
- activation/publishing UI;
- production behavior changes to `BEFORE` semantics;
- current source migration and removal of deprecated compatibility paths.

The configuration prototype must not be connected to `IngestionBatchService`,
`IngestionOrchestrator`, source adapters, Rules Engine, matching or promotion.
