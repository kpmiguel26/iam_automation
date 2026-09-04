# Technical Progress

## Architecture delivered

```text
PySide6 preflight shell
        |
        v
Local Flask/Waitress webapp on 127.0.0.1
        |
        v
SQLAlchemy ORM + local SQLite runtime
        |
        +--> JSON requests and audit files in SharePoint
        +--> XLSX source ingestion and quarantine
        +--> Canonical Worker/Employee domain
        +--> Controlled publication snapshots
```

## Data ingestion flow

```text
SharePoint source folder
        |
        v
File watcher
        |
        v
Import batch and immutable ingestion records
        |
        v
Validation and quarantine
        |
        v
Matching preview
        |
        +--> Existing Worker enrichment
        +--> New Worker candidate
        +--> New engagement
        +--> Discrepancy review
        |
        v
Approval request
        |
        v
Canonical Employee directory
```

## Source adapters

### Roster Lock

- Detected automatically from the synchronized source folder.
- Parsed from XLSX.
- Valid rows are staged in `ingestion_records`.
- Invalid rows are quarantined.
- Approved records can create or enrich canonical Worker/Employee data.

### RSR Supplier Worker Details

- Detected automatically from the synchronized source folder.
- Parsed as a Fieldglass-related historical worker export.
- Vendor is derived from the business content, such as `TTEC` from the Statement of Work.
- Matching considers supplier reference, worker ID and buyer reference.
- Unmatched records remain staged for review and approved promotion.

## Canonical Worker/Employee model

- `workers`: stable internal person identity.
- `worker_identifiers`: NUID, vendor ID, Fieldglass ID, Salesforce ID and source identifiers.
- `worker_engagements`: vendor, SOW, project, role, dates, location and assignment history.
- `worker_source_lineage`: source file, checksum, batch, row and field history.
- `worker_discrepancies`: conflicting values and review status.

Source files are observations, not the master record. A rehire keeps the same Worker ID and creates a new engagement.

## Stability work completed

- SQLite WAL and busy timeout configuration.
- Process-level write coordination.
- Separation of file detection from ingestion transactions.
- Watcher error handling and continued operation after ingestion failures.
- Idempotency by file checksum and source row.
- Versioned database migrations through the migration runner and Alembic-compatible structure.

## Current technical caveats

- The official Fieldglass data dictionary is not approved.
- Some source workbooks contain footer/date rows that correctly enter quarantine but need more precise row detection.
- Browser end-to-end coverage is still limited compared with service-level tests.
- Windows portable packaging still needs a clean test artifact and short-path validation.
- Runtime SQLite and generated request/audit data must remain outside source-control commits.
