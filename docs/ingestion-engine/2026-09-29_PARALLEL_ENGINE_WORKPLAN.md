# Parallel Ingestion Engine — Work Plan

**Date:** September 29, 2026  
**Status:** Discovery and prototype staging work; production import is blocked pending the readiness plan
**Configuration reference:** [Configuration UI Design](./CONFIGURATION_UI_DESIGN.md)  
**Architecture and migration context:** [Ingestion Engine work area](README.md)

## Goal

Start a second, template-driven runtime beside the legacy application. Runtime v2
reads approved source-template snapshots and an explicitly approved Object
Template, watches only the folders selected in those snapshots, and writes
source evidence and object links into its own additive SQLite tables. It does
not write to canonical Employees, legacy ingestion facts, the Rules Engine,
publication, requests or ITSM workflows.

## Coexistence and compatibility

- Runtime services live under `application/parallel_engine/`; its web routes are
  registered inside the normal Flask application under `/engine`.
- The normal application session and CSRF protection are shared. Admins reach
  the engine from the Administration menu. Existing legacy routes and workflows
  remain available in that same application.
- The normal local webapp process starts and stops the runtime-v2 watcher with
  the existing watcher. The separate `parallel_webapp` entrypoint remains a
  compatibility option; it is no longer required to reach the engine.
- Runtime v2 owns a namespaced schema and schema-version table in the current
  local runtime SQLite. Its migration is additive and independent of the legacy
  migration runner.
- The configuration reader reads persisted snapshots directly. It does not call
  legacy ingestion, watcher, matching or persistence services.

## Runtime flow

1. Load the newest approved Object Template and its pinned report-template
   versions. Reject deleted sources, unapproved versions, stale references,
   invalid roots and missing watch folders. Keep the last approved template
   active while a newer draft is being reviewed.
2. Poll configured folders every 120 seconds. Ignore hidden, unsupported and
   out-of-root files. Read only stable files and calculate a SHA-256 signature.
3. Recognize a file using folder membership, extension, filename pattern, sheet
   and the required headers for included source fields. Unknown or ambiguous
   files receive a diagnostic. Recognized files remain pending until an
   Application Admin or Master Admin explicitly authorizes that file.
4. Parse configured CSV/XLSX headers, preserve source row/sheet lineage, apply
   only the template's allow-listed transforms, and record structural
   diagnostics after per-file authorization. Configured date conversion and
   date-skip metadata remain inert.
5. Persist one idempotent v2 batch and its raw/normalized evidence. Pin the
   source-template and Object Template version IDs on the batch. Record the
   authorizer on the file observation. Retry transient file/SQLite failures
   without terminating the watcher.
6. Use exact equality on explicitly transformed Strong identifiers and saved
   cross-source links to attach evidence to a v2 object. Supporting identifiers
   and names remain evidence. Ambiguous matches are flagged for review. Create
   a new object only when the approved Object Template and source identity
   configuration authorize it.
7. Keep object properties source-scoped. This increment does not select merge
   precedence or project values into canonical Employee attributes.

## Object Template approval

The current Object Template repository saves immutable drafts but has no
approval state of its own. Add a separate `engine_v2_object_template_approvals`
table keyed by the existing object-template version ID. An Application Admin
or Master Admin can approve a valid draft from `/engine`; approval does not
rewrite the legacy template row. Approval validates that every pinned report
version is still the newest approved version, active, reachable below the
SharePoint root and structurally linked by configured Strong identifiers.

## Operational view

`/engine` shows watcher health, active pinned sources, pending Object Template
approval, recent batches, observed files, per-file authorization actions,
diagnostics and object/evidence counts. Watcher health and observation data live
only in `engine_v2_*` tables;
legacy watcher sidecars and notifications are untouched.

## Acceptance checks

- The loader excludes source drafts/deletions, requires object approval, honors
  pinned source versions and reports stale object configuration.
- A watcher scan only records discovery/recognition; no batch, evidence or
  object is created until an approver authorizes one pending file.
- CSV and XLSX recognition handles configured sheets/header rows, preserves
  identifier strings and rejects missing/duplicate/ambiguous structure safely.
- Unknown, ambiguous, unsupported and out-of-root files do not create evidence
  or objects; retryable failures leave the watcher alive.
- Exact Strong links attach rows to one object; missing IDs, multiple object
  candidates and unauthorized creation remain reviewable and never merge
  objects incorrectly.
- Reprocessing the same path, checksum and pinned versions returns the original
  batch. Changed content or a newly approved template version gets a new batch.
- The normal application serves `/engine` on the same origin, shares login and
  CSRF state, and protects template and per-file approvals with CSRF and
  approver roles. Existing legacy routes and services remain available.
- Tests prove no writes to Employee, legacy batch/fact, rules, publication,
  request or ITSM tables.

## Completion checklist

- [x] Confirm parallel boundary and compatibility constraints.
- [x] Add immutable runtime contracts, template catalog and namespaced schema.
- [x] Add template-driven CSV/XLSX parsing and structural validation.
- [x] Add batch persistence and source-scoped Strong identity linking.
- [x] Add configured-folder watcher, health and retry tracking.
- [x] Add separate Object Template approval and `/engine` operational view.
- [x] Add a composite host and new launcher without editing the old launcher.
- [x] Add focused runtime, watcher, approval and composite-host regression tests.
- [x] Run focused suite, `git diff --check`, inspect final diff and report risks.

## Approval flow follow-up — 2026-10-01

Object Template approval now lives in the Template Library's Object Template
accordion. The configuration page validates and saves a draft, then returns to
the library, where an Application Admin or Master Admin can approve that exact
saved version after runtime checks. `/engine` is an operational view and
consumes the approved snapshot; it no longer presents an Object Template
approval action. Object source choices use the latest approved report-template
snapshots only.

## Implementation status — 2026-09-29

The new runtime, isolated `engine_v2_*` persistence, configuration snapshot
loader, CSV/XLSX reader, watcher, Object Engine, approval route, `/engine` view,
composite `/legacy` host, and new entrypoint are implemented in new files. The
existing launcher and legacy application modules were not edited. The focused
runtime and web regression suite passes: **23 passed, 1 skipped**. Python
compilation and `git diff --check` also pass.

The combined check of configuration and migration tests has four failures in
legacy expectations: two configuration tests expect the old source-mapping
flow to select Strong identifiers, and two migration tests expect the migration
catalog to stop at v022 although v023–v027 are present. No legacy source,
migration runner, or migration files were changed for this work.

The real configured-folder smoke test remains pending. It requires starting the
new watcher against the current runtime configuration and should be performed
when that operational run is intended; automated tests exercise the watcher
against isolated temporary folders and databases.

## Normal application integration — 2026-09-30

The runtime-v2 blueprint is registered by the normal `create_app` factory at
`/engine`, and the Administration menu links to its dashboard. The normal local
webapp process starts and stops the engine watcher alongside the legacy watcher.
Runtime-v2 persistence remains namespaced and isolated from canonical employee
and ITSM workflows. The configured-folder smoke test is still pending.
