# Ingestion Engine Work Plan

**Work date:** 2026-09-22

**Status:** Phase B/C configuration prototype implemented for review; production lifecycle migration gated

**Related architecture:** [Ingestion Engine Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)

**Configuration design:** [Configuration UI Design](../ingestion-engine/CONFIGURATION_UI_DESIGN.md)

## Objective

Validate the future agnostic ingestion contract through a safe configuration
experience before changing the current production ingestion lifecycle. The
prototype must remain additive, DRAFT-only and isolated from production
persistence, rules, matching and canonical promotion.

## Revised implementation order

1. **Phase A — Architecture baseline**
2. **Phase B — Configuration UI prototype**
3. **Phase C — Draft SourceDefinition + sample preview**
4. **Phase D — Batch lifecycle extraction**
5. **Phase E — persisted SourceDefinition + SourceRegistry**
6. **Phase F — Roster Lock migration**
7. **Phase G — activate published definitions**
8. **Phase H — additional source migration**

Phase D and later phases require a separate explicit approval after the
configuration workflow and draft contract are reviewed. Existing branch work is
preserved; this task does not expand or reconnect the production lifecycle.

## Current execution status

- [x] Architecture baseline and implementation-order decision documented.
- [x] Isolated `/admin/ingestion-sources` configuration page added.
- [x] Frozen draft contracts added; versioned persistence is isolated from runtime ingestion.
- [x] CSV/XLSX sample inspection and bounded preview added.
- [x] Source columns can be included/excluded and their inferred data types can be reviewed or overridden.
- [x] Draft templates can declare identity authority without executing matching or creating employees.
- [x] Tests verify page access, draft editing, identifiers, CSV/XLSX inspection,
  preview diagnostics and production-write isolation.
- [x] Persisted draft/approved template snapshots and a separate template library.
- [x] Template library presents one card per source, with HTMX identity settings and source-level ingestion order.
- [x] Template cards configure the SharePoint-root subfolder, saved/default or custom timezone, selected date/time fields, and an inert user-selected date comparison for future skipping.
- [ ] Runtime `SourceDefinition` adapter and `SourceRegistry`.
- [ ] `SourceRegistry`.
- [ ] Production batch lifecycle extraction or source migration for this revised sequence.
- [ ] Watcher activation, publishing and production configuration integration.

## Guardrails

- Do not modify authoritative external platforms.
- Do not make Business Rules blocking or introduce new `BEFORE` semantics.
- Do not create `ImportBatch`, `IngestionRecord`, `QuarantineRecord` or source
  facts from the configuration page.
- Do not invoke Rules Engine, `EmployeeService`, matching or canonical promotion
  from sample inspection or preview.
- Do not connect the production FileWatchService to draft watched paths.
- Keep configured folder, timezone conversion and skip policies inert until a later runtime phase is approved.
- Do not add database tables or migrations for drafts in this phase.
- Preserve current adapter imports, result shapes and legacy behavior.
- When a later migration moves a function/class to a new file, follow the
  `DEPRECATED` compatibility protocol in `AGENTS.md`.

## Phase A — Architecture baseline

### Objective

Freeze the current boundary and record the approved implementation order.

### Acceptance criteria

- `BEFORE` remains post-staging/post-commit advisory evaluation before `AFTER`.
- Structurally quarantined records remain auditable but are excluded from normal
  Business Rules evaluation during this phase.
- Matching and canonical promotion remain outside generic ingestion.
- The configuration prototype precedes production lifecycle changes.

### Status

Complete. See the architecture baseline and the implementation-order note.

## Phase B — Configuration UI prototype

### Objective

Provide an administrative design laboratory using existing Flask, Jinja,
Bootstrap and server-rendered conventions.

### Scope

- Add the `/admin/ingestion-sources` page and Administration navigation link.
- Provide SOURCE, STRUCTURE, SOURCE SCHEMA and TEST / PREVIEW sections.
- Keep the editing pointer in the signed Flask session; persist template snapshots in SQLite.
- Keep employee/canonical field selection outside this prototype; the future Employee Engine owns it.
- Capture identity governance in the template draft: role, create authority and
  per-field match/create permissions. This is source authority, not employee
  field mapping.

### Non-goals

- No production source activation.
- No watcher integration.
- No activation, watcher configuration or runtime source registry.
- No change to current ingestion services.

### Acceptance criteria

- An administrator can load the page, add/remove draft fields and reset the draft.
- Source columns may be excluded from the draft schema.
- Inferred data types are suggestions and can be overridden by the user.
- Identifier fields remain strings.
- Employee-linked validation/enrichment drafts require at least one included
  Strong identifier selected for matching. Identity Seed drafts with Employee
  UUID creation enabled require at least two distinct included Strong identity
  fields, both selected for matching and individually authorized to create.
  Identity Seed without creation permission still requires one Strong matching
  field; Evidence Only drafts are exempt because they do not link to Employee.
- Only DRAFT actions are presented.

### Status

Implemented for review.

## Phase C — Draft SourceDefinition and sample preview

### Objective

Validate the typed shape and sample interpretation needed by the future generic
engine without making the definition production-owned.

### Scope

- Add frozen draft contracts for source identity, reader, recognition, selected
  source fields, inferred/overridden types, transforms, validations, drift
  policy and identity governance.
- Inspect CSV/XLSX sheets, raw rows, bounded row counts and sample rows.
- Compose and edit multiline header-derived draft field names in memory.
- Suggest types without silently changing configured types.
- Apply only controlled, allow-listed preview transforms.
- Report included/excluded source columns, missing fields, invalid values and drift messages.

### Non-goals

- No persisted `SourceDefinition`.
- No `SourceRegistry`.
- No arbitrary executable transforms.
- No production ingestion, batch creation, rules evaluation, matching or promotion.

### Acceptance criteria

- CSV and Excel sample inspection works with temporary artifacts.
- A user can select one primary header row or multiple context rows; the Master
  Roster fixture composes `NUID · LogonID` and `NPN · LogonID` as separate fields.
- Duplicate or ambiguous source labels remain visible and editable before source-schema selection.
- Leading-zero identifiers remain strings.
- Preview does not write production ingestion tables or facts.
- The policy is saved in the versioned template snapshot but is not consumed by
  the generic ingestion lifecycle. A future Identity Resolver/Employee Engine
  consumes it after fact commitment.
- Invalid draft configuration returns useful messages.

### Status

Implemented for review. See [CONFIGURATION_UI_DESIGN.md](../ingestion-engine/CONFIGURATION_UI_DESIGN.md).

## Phase D — Batch lifecycle extraction

### Objective

Extract generic batch creation, persistence coordination, fact writing and
completion outcomes only after the UI contract is accepted.

### Scope

- Add or retain a typed generic lifecycle service in a new module.
- Preserve the old adapter facade and mark migrated entry points `DEPRECATED`.
- Add characterization/parity tests before switching callers.
- Keep source readers, normalizers and source-specific validators source-owned.

### Non-goals

- No SourceDefinition persistence or registry.
- No AccessNow/RSR migration.
- No matching or canonical promotion changes.
- No new `BEFORE` semantics.

### Gate

Explicit approval required after Phase B/C review. Do not start this phase as
part of the configuration prototype task.

## Phase E — Persisted SourceDefinition and SourceRegistry (in progress)

### Objective

Persist versioned template snapshots and a separate review library now that the
draft contract is usable. Adapt those snapshots to the runtime `SourceDefinition`
and `SourceRegistry` only after the generic lifecycle boundary is proven.

### Gate

Implemented so far: additive SQLite schemas for immutable draft/approved
versions and independent source ordering, card-based library, HTMX identity
configuration and application/master administrator approval. Still required:
runtime registry contract, batch pinning, publication authority and operational
audit policy. Approved templates are not active runtime sources.

## Phase F — Roster Lock migration

### Objective

Move Roster Lock behind the generic engine using the deprecated compatibility
facade and parity tests.

### Gate

Requires production parity evidence for counts, lineage, deduplication, facts,
statuses, rollback and public result shapes.

## Phase G — Activate published definitions

### Objective

Introduce controlled publication and activation only after definition versioning,
authorization and operational rollback are defined.

### Gate

No activation controls belong in the current prototype.

## Phase H — Additional source migration

### Objective

Migrate Master Roster, AccessNow, RSR and future sources one at a time, preserving
legacy facades and source-specific policy.

### Gate

Each source requires its own characterization/parity suite and explicit migration
decision. Matching and canonical promotion remain outside generic ingestion.

## Verification for the current phase

- Focused configuration suite: `10 passed`.
- Full existing suite must be run before handoff.
- `git diff --check` must pass.
- Confirm no database schema, watcher, Rules Engine, canonical promotion or
  existing ingestion contract changed.
