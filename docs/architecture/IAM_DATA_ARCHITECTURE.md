# IAM Data Architecture

## Purpose

Centralize worker contact information from multiple sources without allowing one vendor file to overwrite another source or bypass review.

## Layers

### 1. Source staging

Each source adapter writes immutable source observations to SQLite. A staged record retains the original payload, normalized fields, source file, row number, source checksum and import batch.

### 2. Validation and quarantine

Structural validation, required-field checks, date checks and duplicate detection occur before reconciliation. Invalid records remain in quarantine and generate administrator notifications.

### 3. Reconciliation

Roster Lock and Fieldglass records are matched using a documented identity strategy. The system produces additions, updates, duplicates and discrepancies for review. No source precedence is implicit in code.

### 4. Canonical worker profile

The canonical profile is implemented in SQLite as `workers`, `worker_identifiers` and `worker_engagements`. A worker has an internal immutable ID; vendor, Fieldglass, NUID and Salesforce identifiers remain external aliases. Rehires reuse the worker identity and create a new engagement.

### 5. Downstream publication

Approved records become requests or controlled writer operations. Salesforce, NICE IEX and other templates are generated from approved canonical data. Access publication remains an explicit snapshot operation.

## Initial Entity Set

| Entity | Purpose |
|---|---|
| `import_batches` | One execution or source-file version |
| `ingestion_records` | Source row staging and lineage |
| `quarantine_records` | Invalid or disputed source rows |
| `workers` | Canonical worker profile |
| `worker_identifiers` | External source identifiers |
| `worker_engagements` | Vendor/project/assignment history |
| `worker_source_lineage` | Per-field source evidence |
| `worker_discrepancies` | Conflicts requiring review |

Roster Lock remains staging-first. An administrator explicitly promotes a staged record into a pending canonical worker and engagement; the watcher never performs that promotion automatically.

## Employee workspace

Authenticated users can view `Operations > Employees`. The directory supports search and filters, while each profile exposes identity, engagements, source identifiers, lineage and discrepancies. Administrative reconciliation actions remain protected by backend authorization.

## Concurrency and Refresh

The watcher may detect a new file while a user is working. Detection and staging are safe because they append a batch and do not replace the local runtime snapshot. Workspace SQLite refresh remains controlled and is blocked when local publication work is pending.
