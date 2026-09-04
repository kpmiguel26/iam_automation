# Roster Lock Ingestion Foundation

> **Historical record — 2026-07-29.** Current status is maintained only in
> [`../../../STATUS.md`](../../../STATUS.md).

**Branch:** `feature/iam-data-ingestion-foundation`  
**Date:** 2026-07-29  
**Scope:** first automated source ingestion increment

## Objective

Monitor the SharePoint-synchronized `rosterlocks/` folder and stage each new or changed Roster Lock workbook in local SQLite. The first increment validates and preserves source records; it does not yet publish the canonical worker entity or write to Access.

## Source Boundary

Roster Lock is a vendor source. Its stable source key is:

```text
source_system + vendor_name + vendor_employee_id
```

The vendor employee ID is not treated as the final IAM worker ID. Fieldglass reconciliation will determine the canonical worker identity later.

Supported workbook variants currently observed:

- `Vendor employee ID`
- optional leading `FG Status`
- `Employee first name`, `Employee last name`, email, vendor, dates, program, project, job title and status

The adapter normalizes header whitespace and case, accepts the optional `FG Status`, and requires `Vendor employee ID`.

## Automated Flow

1. The permanent watcher polls `rosterlocks/*.xlsx` every second while the local webapp is running.
2. A new or changed file is identified by path, size and modification signature.
3. The Roster Lock adapter reads the workbook in read-only mode.
4. Every row is staged with source file, row number, checksum, normalized fields and original payload.
5. Rows without a vendor employee ID are placed in quarantine.
6. Duplicate keys inside the same file are placed in quarantine; they are never silently overwritten.
7. A notification is sent to active administrators with the import result.
8. The import center exposes the batch and quarantine records for review.
9. No canonical worker, Fieldglass merge or Access publication occurs automatically.

## Data Architecture

```text
SharePoint/rosterlocks/*.xlsx
        |
        v
File watcher + signature ledger
        |
        v
Roster Lock adapter
        |
        +--> import_batches
        +--> ingestion_records (source staging and lineage)
        +--> quarantine_records (invalid or conflicting rows)
        +--> notifications
        |
        v
Future reconciliation layer
        |
        +--> canonical_workers
        +--> worker_source_lineage
        +--> worker_discrepancies
        |
        v
Approved request / publication workflow
```

## Source Precedence

No precedence rule is assumed in this increment. The future reconciliation policy will be explicit:

- Roster Lock supplies vendor staffing and onboarding intent.
- Fieldglass supplies the authoritative worker/engagement record when its official contract is approved.
- Salesforce and NICE IEX are downstream exports, not source systems for the canonical worker record.

Conflicting values must be retained as discrepancies with source lineage, not silently replaced.

## Safety Rules

- Local SQLite is the working store.
- The published Access database remains outside automatic ingestion.
- A source file is never deleted or moved by the watcher.
- Reprocessing a changed workbook creates a new import batch and preserves history.
- Quarantine is recoverable and auditable.
- Canonical worker merging requires a separate business-approved mapping and preview.

## Deliverables

- [x] Branch created from the merged `main` baseline.
- [x] Permanent watcher recognizes the Roster Lock folder.
- [ ] Roster Lock adapter and staged record repository.
- [ ] Import center preview for staged rows and quarantine.
- [ ] Fieldglass contract and reconciliation design.
- [ ] Canonical worker entity and source lineage migration.
- [ ] Integration and user acceptance tests with the official templates.
# Follow-up: RSR enrichment

The next source adapter is documented in `2026-07-30_RSR_WORKER_DETAILS_ACTION_PLAN.md` and follows the canonical model in `docs/architecture/WORKER_EMPLOYEE_CANONICAL_ARCHITECTURE.md`. Roster Lock remains the source that can create a staged worker candidate; RSR enriches only an existing canonical worker after matching and approval.
