# RSR Supplier Worker Details: Action Plan

## Objective

Ingest the `rsrsuplierworkerdetails` SharePoint folder automatically, reconcile its worker details against the canonical Employee domain, and keep every source value traceable without making an Excel row the identity of a worker.

## Delivery Sequence

- [x] Confirm the RSR workbook structure and identify stable keys.
- [x] Add a source-specific RSR ingestion adapter.
- [x] Stage the workbook as one import batch, including quarantine for incomplete rows.
- [x] Add deterministic matching preview before any canonical update.
- [x] Match by Supplier Reference first, then RSR Worker ID and Buyer Reference.
- [x] Preserve ambiguous and conflicting values for review.
- [x] Create a shared review request for the discovered RSR source file.
- [x] Route approved source records to selective Employee Updates review.
- [x] Apply an approved source record individually to an existing Employee or create a new Employee candidate.
- [x] Derive the business vendor from Fieldglass Statement of Work while preserving the full SOW.
- [x] Repair legacy RSR engagements that were labeled with the adapter name instead of the business vendor.
- [x] Add watcher discovery and retry-safe notifications.
- [ ] Add Fieldglass matching and source precedence rules.
- [ ] Add reviewer UI for resolving discrepancies.
- [ ] Add Salesforce and NICE IEX export mappings after official templates are approved.

## Operating Rules

1. RSR never creates or updates a canonical Employee merely because a file arrived; bulk approval is required.
2. A direct identifier match is required for enrichment. An unmatched row may create a new historical Employee only after approval.
3. A rehire keeps the same `worker_id` and receives a new engagement when the work order is new.
4. Ambiguous matches remain staged and are not included in an approval request.
5. Conflicts retain current and incoming values in `worker_discrepancies`.
6. The source file request is shared per batch, but canonical creation and enrichment happen one worker at a time from Employee Updates.
7. The published Access database remains outside this ingestion transaction; runtime SQLite is the working store.

## QA Exit Criteria

- The 615-row reference workbook can be staged in one operation.
- Re-running the same file is idempotent by source path and SHA-256 checksum.
- The watcher continues after a malformed workbook or temporary SQLite contention.
- Existing Roster Lock and request approval tests remain green.
- RSR rows are visible in Imports and quarantine with match status and reason.
- `MATCHED` and `UNMATCHED` rows are presented in Employee Updates; ambiguous and conflicting rows remain explicitly reviewable.
- Approval of the source request does not write canonical Employees. An administrator applies each reviewed row individually, preserving source lineage and history.
- The adapter label `RSR_SUPPLIER_WORKER_DETAILS` is never displayed as the business vendor when the SOW identifies `TTEC`, `Concentrix`, or another supplier.
