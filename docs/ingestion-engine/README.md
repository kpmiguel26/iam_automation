# Ingestion Engine work area

This folder marks the dedicated work area for the source-agnostic Ingestion
Engine branch.

The approved design and staged work plan remain in the repository's canonical
documentation locations:

- [Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)
- [Work plan](../work/2026-09-22-ingestion-engine-work-plan.md)

The current phase is the isolated configuration prototype and draft contract.
It validates SOURCE, SCHEMA, MAPPING, VALIDATION and TEST / PREVIEW without
connecting the saved templates to production ingestion. The library now persists
versioned draft/approved report templates and a versioned, user-named Template
Object definition. These remain configuration records; they are not the runtime
`SourceDefinition`/`SourceRegistry` and do not drive imports, matching or object
creation.

- [Configuration UI design](CONFIGURATION_UI_DESIGN.md)
- [Four-source match findings (2026-09-24)](2026-09-24-four-source-match-findings.md)

## Parallel architectures and deprecation status

Two paths currently coexist:

| Path | Status | Owns today |
|---|---|---|
| Legacy runtime ingestion | **Active; selected entry points marked `DEPRECATED` for migration tracking** | Hard-coded source dispatch, source-specific ingestion services, source-specific canonical Employee matching and application workflows. |
| New Ingestion Engine configuration | **Active configuration prototype; not runtime-connected** | Versioned report-template settings, identity authority, order, SharePoint subfolder/date policies and Template Object definitions/relationships. |

`DEPRECATED` here marks an intended migration target; it does not disable the
current path. No legacy implementation has been deleted or switched out. Runtime
replacement remains gated on an executable SourceRegistry/Object Engine and
source-by-source characterization/parity. See the [work plan](../work/2026-09-22-ingestion-engine-work-plan.md).
