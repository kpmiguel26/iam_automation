# Ingestion architecture

**Status:** Refactored format adapters; SQLite consumer migration remains active.

This document describes the Python ingestion structure currently implemented
on `fix/sqlite-relational-rule-evaluation`. It is the working reference while
the remaining consumers move from source JSON to relational facts.

The next write-model design is documented in
[Write model architecture](./WRITE_MODEL_ARCHITECTURE.md). It defines the
canonical `employee` entity, source-specific write tables, identity links and
AccessNow status ownership.

## Package layout

```text
iam_automation/
├── application/
│   ├── ingestion/
│   │   ├── common.py          # stable file reads and source timestamps
│   │   ├── contracts.py       # result contract and compatibility helpers
│   │   ├── dedup.py           # payload hashing and latest-fact lookup
│   │   └── orchestrator.py    # source-system to adapter dispatch
│   ├── accessnow_ingestion_service.py
│   ├── master_roster_ingestion_service.py
│   └── roster_lock_ingestion_service.py
├── source_adapters/
│   ├── accessnow/             # CSV/XLSX reader, normalizer, validator, merger
│   ├── master_roster/         # XLSX reader, normalizer, validator
│   ├── roster_lock/           # XLSX reader, normalizer, validator
│   ├── rsr_supplier/          # Fieldglass reader and normalizer
│   └── rsr_supplier_worker_details.py  # public adapter facade and apply workflow
└── infrastructure/sqlite/
    ├── orm.py
    └── star_schema_writer.py  # relational source facts and reconstruction
```

The source-specific format modules do not open database sessions. They read
rows, normalize labels and values, merge source-specific reports where needed,
and return data to the application service. The application services own batch
creation, quarantine records, deduplication decisions and the import boundary.
The SQLite writer owns ORM persistence of source snapshots and field facts.

## Runtime flow

```text
file path
  → read_stable_bytes
  → source reader
  → normalizer / report merger
  → source validator
  → IngestionOrchestrator
  → import_batch + ingestion_records + quarantine_records
  → StarSchemaWriter (fact_source_snapshot + fact_worker_field)
  → commit
  → clear valid-row legacy JSON
  → post-commit rules, review, matching or approved promotion
```

`AccessNow` reads a folder and merges active and termination reports before the
batch is staged. `Master Roster`, `Roster Lock` and `RSR` read one workbook at a
time. A source row is not canonical employee data: matching and promotion are
separate decisions.

## Boundaries

- Format adapters know file layouts and source vocabulary.
- Application ingestion services know batch lifecycle, quarantine and source
  keys.
- `IngestionOrchestrator` selects an adapter; it does not evaluate rules or
  promote workers.
- `StarSchemaWriter` is an infrastructure component and writes through the
  SQLite ORM session supplied by the caller.
- `application/star_schema_writer.py`, `stable_file_read.py` and
  `ingestion_dedup.py` remain compatibility facades for existing imports.
- RSR and AccessNow still contain matching and approved-apply code in their
  public facades. That code is scheduled for extraction into application
  reconciliation and promotion services.

## Current persistence behavior

Valid rows write relational facts first. Their `normalized_json` and
`payload_json` values are cleared after the fact transaction in a separate
cleanup transaction. Quarantine rows retain JSON so malformed input remains
reviewable. The current writer stores changed fields as source deltas and
reconstructs a complete row by walking prior observations; this is an explicit
transition behavior and must be resolved before retention cleanup.

## Step-by-step migration sequence

1. Repair and test the watcher dispatch path. The current `scan_once` contains
   an early return that prevents its historical processing and notification
   branch from running.
2. Move source payload reads in employee projection, rehire alerts, reports
   and history to `StarSchemaWriter.payload_for_record` or relational queries.
3. Extract a shared `IngestionBatchService`/unit-of-work boundary so each
   source service does not construct the same batch and fact transaction.
4. Move RSR and AccessNow matching, discrepancy creation and approved apply
   into application services; leave source adapters format-only.
5. Rebuild history readers from `fact_worker_field_history` and validate that
   the history UI displays new relational versions.
6. Identify the launcher's active SQLite runtime and validate migrations,
   rollback, counts and lineage on a disposable copy.
7. Define complete-snapshot versus delta retention, then make cleanup atomic
   and remove legacy JSON only after every consumer is relational.

The full regression suite still has five known watcher failures caused by the
existing early-return behavior. Direct ingestion, rule, report and relational
transition tests are the acceptance checks for the refactoring increments
until that watcher path is repaired.
