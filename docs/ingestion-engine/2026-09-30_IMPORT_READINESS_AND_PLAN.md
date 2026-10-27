# Import Engine Readiness Review and Implementation Plan

**Review date:** September 30, 2026
**Readiness:** Not ready for production ingestion
**Reviewed runtime:** Parallel Ingestion Engine v2 on the local `runtime.sqlite`

## Progress recorded October 27, 2026

The code defines additive schema version 7, including stable object-type
identity, per-source Strong Identifier values, source facts/property values,
and v2 advisory rule findings. The v2 ingest path records identifier claims
and facts with accepted evidence/object links. It now reads active current
Business Rule versions and evaluates BEFORE/AFTER record conditions against
v2 parsed rows, saving matches with v2 batch, source, evidence and object
lineage. Rule evaluation and finding persistence failures are diagnostics and
do not reject rows or undo a completed batch. The legacy rule execution
service is not called because it assumes legacy batches/records. Object
Templates now let an administrator map each included source field to a shared
canonical property key; v2 writes that key while retaining the original source
field and source lineage. Values from different sources remain separate. No
authority/priority, transform, winner selection, or conflicting-value finding
is implemented yet. Source-binding history, template-safe physical-data
lifecycle, quarantine/replay, finding disposition workflow, and end-to-end
parity remain open. A read-only dashboard now displays recent v2 findings.
The dashboard also exposes the latest 50 quarantined rows with their source,
row number, validation diagnostics, raw values, and normalized values. This is
read-only triage; correction, rejection, and idempotent replay remain open.
Existing evidence JSON matching remains as a compatibility
fallback for prior rows. The authorization gate remains disabled, and no
migration was applied to the local runtime in this code change.

## Readiness decision

The current v2 code can parse, validate, quarantine, match, and persist prototype
records. It is not the import flow described by the product requirements. It
does not populate the application's physical star schema or perform
dependency-safe template changes, and it lacks complete quarantine/replay and
finding review workflows. Its advisory rule adapter reads current configured
record rules and stores matches in the v2 evidence model; it does not invoke
legacy batch execution. The authorization route remains gated off. Folder
discovery and file recognition remain active.

## Implemented first step: persist file discovery and analysis

The additive engine schema is now version 4. Discovery writes one row per file
and applicable pinned report version to `engine_v2_file_analyses`, linked to
`engine_v2_file_observations`. It records the file path/name, SHA-256, size and
modified time, configured source order, selected worksheet, detected/required/
missing/unknown headers, individual recognition checks, outcome and diagnostics.
It stores no source row values.

This step does not create batches, evidence, object instances, physical object
tables or Strong Identifier values. A uniquely recognized file remains pending
explicit authorization; an unrecognized or ambiguous file records its reason.
The authorization route remains gated, so this discovery persistence is not an
import execution path.

## Implemented template-removal safeguard

The Template Library now previews references and Parallel Engine data before
removing a report. Remaining Object Template bindings for that report's
properties, Strong Identifiers and Strong links block deletion until detached;
multi-report objects must also unlink the report. If it is the object's only
report, removal requires a separate confirmation and purges all v2 batches,
evidence, evidence links, instances and runtime approvals for that object type.
When other report evidence still supports an instance, that instance remains;
instances left without evidence are removed. File observation/analysis history,
template versions and an audit summary are retained. Legacy import and employee
tables are not changed. As physical property, identifier and fact tables are
added, their dependent rows must be added to this same transactional cascade.

The engine also has a separate row-staging operation for the next import phase.
It records the approving actor and time on the batch, persists each parsed row
as staged evidence or quarantine with its validation diagnostics, and never
creates an object instance or identifier. The app's processing route remains
paused; this staging operation is not yet exposed through the UI while the
physical object model and Rules Engine coordinator are unfinished.

## Code review findings

### Physical model and object properties — blocking

- An Object Template defines a user-named object type/creator, not one Employee
  instance. It selects report templates and configures properties, identifier
  bindings and relationships; the model must support types beyond Employee.
- It must compose canonical properties from fields across pinned report
  templates with explicit source authority and conflict behavior. Identity
  matching, property mapping and relationships between object types are
  separate configurations.
- Each distinct instance created during ingestion receives an immutable,
  system-generated UUID. It keys that instance's properties, facts,
  identifiers and links. Strong Identifier values remain separate business
  keys and can resolve multiple report rows to the same instance.
- Keep the engine's physical model independent from legacy `worker_id` and
  `dim_employee.employee_key`. Importing an engine object must not write legacy
  Employee tables as a side effect.
- `engine_v2_objects` stores object ID, stable object-type ID, template
  version, creation time, and status. Schema version 5 adds source facts and per-source property-value
  rows, linked to object UUIDs and row evidence. Values are stored as JSON with
  declared source data type and source-field lineage; they are not yet composed
  into canonical object properties.
- `engine_v2_objects.object_id` is an engine-generated instance UUID and the
  table remains metadata-only. Schema version 5 adds shared source-fact and
  source-property value tables; schema version 6 adds stable type identity and
  physical Strong Identifier claims. Canonical property composition is still
  missing.
- Create or evolve physical schema once per object type, not once per Employee
  or file. Choose additive migrations for template-defined
  schemas or shared typed property tables before enabling physical writes.
- `engine_v2_evidence` stores raw and normalized row values as JSON. Object
  links point from `engine_v2_object_evidence` to that evidence.
- Runtime v2 does not write the existing physical star schema. The application
  already has tables such as `dim_employee`, `bridge_employee_identifier`,
  `source_field_mapping`, and source fact tables in its v0013/v0015 schema
  migrations. Runtime v2 currently bypasses them.
- Object and source definitions are versioned JSON snapshots. There is not yet
  a runtime v2 migration that creates/evolves a canonical physical model from
  an approved Object Template. The shared source-fact/property-value tables are
  additive and do not create per-object tables.

### Strong identifiers and template lifecycle — blocking

- Strong Identifier definitions from source templates must be attachable,
  detachable and deletable independently of the object instance UUID.
- Strong identifier definitions and match links remain in the versioned Object
  Template JSON. Schema version 6 adds `engine_v2_strong_identifiers`, with
  source field, exact stored value, object type/object UUID and evidence/batch
  provenance. Exact equality preserves the prior matcher behavior; identifier
  normalization, protected-value storage and attach/detach lifecycle remain
  undecided.
- The physical identifier claim is unique per object type, source and field
  value. Configured cross-source links query those claims and quarantine rows
  whose configured identifiers resolve to multiple objects. The prior
  `STAGED` evidence JSON matcher remains active alongside the indexed lookup
  to preserve prototype matching and expose conflicts; it is not yet removed
  or fully backfilled.
- Deleting a report template is currently a soft removal recorded in
  `source_template_lifecycle_events`; it does not cascade through v2 objects,
  identifiers, or evidence. Object Templates are append-only drafts and do not
  have a delete workflow.
- Catalog loading rejects an approved Object Template if its pinned source was
  deleted or changed. It does not preview affected objects or links, prevent an
  orphaned object, or ask the administrator to update the Object Template.
- Before removing a template with Strong Identifiers, require Object Template
  edits, validate that those bindings are detached or replaced, and block the
  delete if an object/link would be orphaned. If it is the sole template, warn
  that its deletion removes all data owned by the object and require explicit
  confirmation. Validate and cascade in one transaction.

### Rules and validation — partially implemented

- The existing Rules Engine is integrated with the legacy ingestion pipeline.
  Its legacy execution service reads legacy `import_batches` and
  `ingestion_records`; v2 has a separate adapter that reads active current
  rule versions and evaluates record conditions against parsed v2 row payloads.
- Matched advisory results are persisted to `engine_v2_rule_findings`, linked
  to v2 batches, evidence, source version and an object UUID when one exists.
  V2 does not write legacy `rule_findings` or legacy quarantine rows.
- The v2 adapter currently supports `RECORD_CONDITION` rules whose fields are
  available in the current source row. Cross-source relationship conditions,
  finding disposition, pagination/filtering and rule parity characterization
  remain outstanding. A read-only dashboard lists the latest 50 findings and
  reports total/open counts. Evaluation/persistence failures are recorded as batch
  warnings when possible and never block ingestion.
- Source-scoped rules now use an explicit Business Rules source key stored in
  each report template, with the internal template key as the default fallback.
  Set an explicit key when those identifiers differ. Existing approved source
  templates must be edited, validated and approved; then the approved source
  version must be re-pinned and re-approved in the Object Template before the
  new mapping takes effect at runtime.
  Composite and cross-source conditions remain unsupported by the v2 adapter.
- Existing BEFORE/AFTER checks are advisory pipeline findings. They are not a
  v2 import gate and do not decide whether an invalid v2 row should be blocked,
  quarantined, or accepted with a warning.
- V2 validates configured field types and constraints and stores invalid rows
  as `QUARANTINED` evidence with diagnostics. It does not create the standard
  quarantine facts or provide a complete correct-and-replay workflow.
- The per-file button previously called `authorize_and_process()`, which
  directly called `ingest_file()`. That path wrote v2 batches, evidence and
  object IDs. It is now disabled by the runtime feature gate; the handler also
  rejects direct POSTs.

## Local database review

The local database was opened with SQLite `mode=ro`; this review did not modify
it. At the review time it contained:

| Runtime v2 data | Count / result |
|---|---:|
| File observations | 5, all `PROCESSED` |
| Batches | 5 |
| Rows in batches | 111 |
| Staged evidence rows | 36 |
| Quarantined evidence rows | 75 |
| V2 object rows | 36 |
| Object-evidence links | 36 |
| Rows linked to existing objects | 0 |
| SQLite foreign-key violations | 0 |

All 75 quarantined rows have the diagnostic `production_start_date is not a
valid date value.` The v2 rows are in `engine_v2_batches`,
`engine_v2_evidence`, `engine_v2_objects`, and `engine_v2_object_evidence`.
The evidence JSON contains the row values; the object rows themselves are
metadata only.

Legacy tables had 713 `ingestion_records`, 5 `import_batches`, and 711
`workers`. Their latest legacy ingestion batch and record timestamps were July
30, 2026, before the v2 processing at 19:15 UTC on September 30. Those legacy
tables were not changed by the five v2 batches.

## Implementation plan

### Phase 0 — Hold processing and classify prototype data

- Keep the processing feature gate off. Continue read-only discovery and
  recognition only.
- Keep the 36 prototype object rows and associated evidence isolated and
  clearly labeled. Do not merge them into Employees or legacy facts.
- Decide separately whether prototype rows should be retained as test evidence
  or removed. Any cleanup needs a backup, a dependency check, and an explicit
  reviewed operation; do not make cleanup part of template deletion.

### Phase 1 — Physical object and star-schema contract

- Define the physical contract between an approved Object Template, each
  source template, its fields, object properties, Strong identifiers, and
  source provenance.
- Use one immutable, generated object UUID as the identity key. Keep source
  Strong Identifier definitions and values separate, with explicit
  attach/detach associations to that UUID.
- Build a generic engine-owned model for user-defined object types: dimensions,
  identifier bridges and source facts. Add additive versioned migrations for
  missing structures; do not create tables per object instance or derive table
  names from raw uploaded headers or file names.
- Canonical property keys can now group included fields across source reports,
  while preserving source-specific values and lineage. Source priority/
  authority, transforms, winner selection and conflict diagnostics remain
  unimplemented; the engine does not silently overwrite a source value.
- Materialize each object and its properties into engine-owned physical tables
  joined by its UUID. Store each source observation in a physical source fact
  with batch, source version,
  source file/checksum, row number, and object reference.
- Materialize every Strong identifier with its type, normalized value,
  object, source, source field, template version, validity, and audit
  provenance. Add uniqueness constraints for the approved matching scope and
  foreign keys to the object and source model.
- Record the physical schema version used by each import batch so later
  template versions can evolve tables without reinterpreting historical rows.

### Phase 2 — Template evolution, deletion, and relationship safety

- Add a read-only impact preview before a template or Strong identifier is
  changed or removed. Show affected object counts, identifiers, facts,
  cross-source links, and objects supported only by the target template.
- Block deletion until Strong Identifier bindings from the target template are
  detached or replaced in the Object Template and the saved definition passes
  validation.
- When deleting the only source template, warn that the operation removes all
  data owned by the object and require an explicit final confirmation.
- A real template delete removes the physical data owned by that template,
  including its facts and identifier values, after the impact and detachment
  checks pass. Preserve a deletion audit record and immutable version metadata
  needed to explain the change; do not retain deleted Strong Identifiers as
  archived active matching keys. The sole-template case removes all data owned
  by that Object Template after explicit confirmation.
- Use restrictive foreign keys for identifiers or links referenced by
  imported objects. In one transaction, validate that every active object
  retains the minimum valid Strong identifiers and that no link becomes
  orphaned.
- If a removal would invalidate object identity or break a match link, block
  the deletion and ask the administrator to update the Object Template,
  replace the identifier, or explicitly resolve the affected links first.
- Add audit records for template changes, identifier changes, link decisions,
  and any approved retirement of physical structures.
- Add typed relationships between user-defined object types, such as Employee
  to Vendor. Configure cardinality and map a source field to a target object's
  Strong Identifier; persist the relationship UUIDs and evidence lineage.
- Resolve imports in dependency order. An unresolved or ambiguous target
  relationship goes to review/quarantine and is never guessed from a display
  name.

### Phase 3 — Import coordinator and Rules Engine adapter

- Implement one coordinator with explicit stages: authorization, stable-file
  verification, recognition, parsing, normalization, structural validation,
  BEFORE rules, Strong-identifier matching, physical fact/object writes,
  AFTER rules, and final batch status.
- Adapt rule evaluation to v2 batch/evidence contracts. Do not write v2 rows
  into legacy `ingestion_records` merely to reuse the existing repository.
- Define rule outcomes before enabling imports: which configured rule results
  block the batch, quarantine a row, or produce a warning. Persist rule
  version, result, and evidence with the batch.
- Execute physical writes and identifier registration transactionally. A
  failure must roll back the affected object/fact/identifier writes while
  preserving a diagnostic batch outcome.

### Phase 4 — Quarantine, correction, and replay

- Persist file-level and row-level errors with stable codes, field/row
  locations, and raw evidence.
- Separate structural validation errors, business-rule findings, ambiguous
  identity matches, and database failures in the UI and data model.
- Provide a review action to correct or reject quarantined rows and replay
  them idempotently against the pinned source and Object Template versions.
- Prevent a partially successful retry from duplicating facts, identifiers,
  objects, or links.

### Phase 5 — Acceptance, controlled enablement, and cutover

- Add tests for physical model creation/evolution, identifier uniqueness,
  strong-link matching, ambiguity, orphan prevention, template retirement,
  rule outcomes, quarantine/replay, transaction rollback, and idempotent retry.
- Prove referential integrity after create, update, delete, and failed import;
  prove legacy Employee and ingestion tables remain untouched until an
  explicit migration/cutover is approved.
- Run end-to-end tests on an isolated copy of the runtime database and a
  representative folder. Inspect every generated object, property, identifier,
  fact, link, rule result, and quarantine row.
- Enable file processing only after acceptance checks pass and the operational
  owner approves the reviewed result. Then begin source-by-source cutover.

## Acceptance criteria for enabling import

- Every imported object and property is queryable from physical tables; no
  required object state exists only in JSON.
- Every object has one stable generated UUID used by its properties, source
  facts, identifier values and relationships.
- Every Strong identifier has a physical row, provenance, normalized value,
  and enforced uniqueness in its documented scope.
- Canonical properties can be populated from different report templates with
  saved authority/priority and conflict behavior; each value retains source
  and template-version provenance.
- A many-to-one Employee-to-Vendor relationship resolves by configured target
  Strong Identifier, preserves its evidence lineage, and reports unmatched or
  ambiguous keys without creating a wrong link.
- Template changes/deletions cannot silently orphan objects or break links;
  Strong Identifier bindings must be detached or replaced first; the user
  receives an impact preview and a clear remediation path. Deleting the sole
  template has an explicit full-object-data warning and confirmation.
- Configured import rules run against the v2 batch at the documented phases,
  and their block/quarantine/warn outcomes are persisted.
- Invalid, ambiguous, and database-failed rows have distinct diagnostics and
  safe quarantine/replay behavior.
- The import transaction is idempotent and passes foreign-key and orphan
  checks; processing remains disabled until the full acceptance suite passes.
