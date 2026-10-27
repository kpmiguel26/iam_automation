# Ingestion Engine work area

This folder marks the dedicated work area for the source-agnostic Ingestion
Engine branch.

The configuration library persists versioned report templates and a
user-named Template Object definition. The parallel runtime reads approved
snapshots, and its watcher discovers and recognizes files. The early v2
processor was exercised and wrote prototype evidence and object IDs into
`engine_v2_*`. The current implementation adds stable object-type identity,
physical Strong Identifier claims, source facts/property values, configurable
canonical property keys that preserve per-source values, and an advisory Rules
Engine adapter that records v2 findings with source/evidence lineage. Report
templates can map their internal source key to the legacy
Business Rules source catalog. The engine dashboard displays recent v2 findings
and read-only triage details for up to 50 quarantined rows. It still lacks
canonical property authority/priority and conflict handling, template-safe
data lifecycle, composite/cross-source rule parity, finding disposition
controls, quarantine correction/replay, and acceptance checks. Existing approved templates need an explicit
source mapping when their internal key differs from the Business Rules source
key. File processing remains gated off
until the import path and acceptance checks are complete. Runtime v2
is registered inside the normal authenticated Flask application at `/engine`;
the normal app starts and stops its watcher with the existing local webapp
process. The Source Update Review engine panel reports the live watcher thread
state, shows a small spinner during scans or file processing, and counts files
checked in the current or most recent discovery cycle.

Object Template drafts are now approved from their card in the Template
Library after configuration validation. The engine dashboard displays runtime
state and consumes the latest approved snapshot; it does not approve Object
Templates.

- [Configuration UI design](CONFIGURATION_UI_DESIGN.md)
- [Four-source match findings (2026-09-24)](2026-09-24-four-source-match-findings.md)
- [Import readiness review and implementation plan (2026-09-30)](2026-09-30_IMPORT_READINESS_AND_PLAN.md)
- [Template creation, library, and Object Template review (2026-10-01)](2026-10-01_template_creation_library_object_review.md)
- [Import Engine design handoff for the next work session (2026-10-01)](2026-10-01_import-engine-design-handoff.md)

## Parallel architectures and deprecation status

Two paths currently coexist:

| Path | Status | Owns today |
|---|---|---|
| Legacy runtime ingestion | **Active; selected entry points marked `DEPRECATED` for migration tracking** | Hard-coded source dispatch, source-specific ingestion services, source-specific canonical Employee matching and application workflows. |
| New Ingestion Engine | **Discovery integrated; stable identity/source-fact, canonical property-key mapping, and advisory rules slices implemented in code; production ingestion blocked** | Versioned report templates with explicit Business Rules source mapping and canonical property keys, isolated watcher, stable object-type UUID for the current Employee Profile type, Strong Identifier claim table, source facts/property values, v2 advisory findings, and dashboard review visibility. Property authority/conflict policy, template lifecycle, composite/cross-source rule parity, finding disposition, quarantine/replay, and acceptance checks remain incomplete; the processing gate stays off. |

`DEPRECATED` here marks an intended migration target; it does not disable the
current path. No legacy implementation has been deleted or switched out.
Runtime v2 remains isolated from legacy ingestion and does not write canonical
Employee data. Do not enable production processing until the [readiness plan](2026-09-30_IMPORT_READINESS_AND_PLAN.md)
acceptance criteria pass. The [parallel runtime work plan](2026-09-29_PARALLEL_ENGINE_WORKPLAN.md)
and [configuration design](CONFIGURATION_UI_DESIGN.md) describe the existing prototype.
