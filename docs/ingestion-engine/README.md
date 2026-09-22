# Ingestion Engine work area

This folder marks the dedicated work area for the source-agnostic Ingestion
Engine branch.

The approved design and staged work plan remain in the repository's canonical
documentation locations:

- [Architecture](../architecture/INGESTION_ENGINE_ARCHITECTURE.md)
- [Work plan](../work/2026-09-22-ingestion-engine-work-plan.md)

The current phase is the isolated configuration prototype and draft contract.
It validates SOURCE, SCHEMA, MAPPING, VALIDATION and TEST / PREVIEW without
connecting to production ingestion. Persisted SourceDefinition, SourceRegistry,
batch lifecycle extraction, source migrations, matching and canonical promotion
remain gated for later phases.

- [Configuration UI design](CONFIGURATION_UI_DESIGN.md)
