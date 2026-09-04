# Star Schema from Zero

## Decision

For the testing reset, the runtime database will be rebuilt from an empty
SQLite file using a relational star schema. The original Excel files remain in
the synchronized SharePoint/OneDrive folders. SQLite stores metadata,
reportable facts and governed values; it does not store Excel binaries or full
row JSON copies.

## Model

```text
                         dim_date
                            |
dim_source ── fact_source_snapshot ── dim_worker
      |             |                  |
      |             +── fact_termination
      |             +── fact_assignment
      |             +── fact_worker_field ── dim_field
      |
      +── import_batch (file/checksum/retention control)
```

### Dimensions

- `dim_worker`: stable employee identity and canonical identifiers. One row per
  employee, not one row per import.
- `dim_source`: `ACCESSNOW`, `ROSTER_LOCK`, `MASTER_ROSTER` and supplier
  sources.
- `dim_field`: approved report/rule fields with data type, sensitivity,
  reportable flag and rule-enabled flag.
- `dim_date`: calendar attributes for date rules and reporting.
- `dim_vendor`: normalized vendor reference where the report requires it.

### Facts and controls

- `import_batch`: one row per imported Excel/report, including source, file
  name, checksum, imported time, row counts, status and retention rank.
- `fact_source_snapshot`: one row per employee/source/batch, containing only
  stable typed fields needed for comparisons and report joins.
- `fact_termination`: termination events and dates from AccessNow, linked to
  the source snapshot and employee.
- `fact_assignment`: vendor, work order, NPN, role, supervisor and assignment
  attributes from the appropriate source.
- `fact_worker_field`: governed extensible values for fields not yet promoted
  to a typed fact column. It uses `dim_field`; it is not a JSON bag.
- `rule_finding`: alert evidence linked to employee, source and import batch.

Every fact includes `batch_id`, `source_id` and `observed_at_utc`. This allows
comparisons between snapshots without duplicating the entire employee profile.

## Retention policy

The database keeps the latest three completed batches for each
`source_system + report_type`. A batch is eligible for cleanup only when:

1. its successor batch imported successfully;
2. its facts passed row-count and key validation;
3. the original Excel is still present in the synchronized folder or has been
   explicitly archived;
4. a backup was created; and
5. the administrator confirms the cleanup in Administration.

The cleanup deletes old snapshot facts and import metadata only. It does not
delete `dim_worker`, rule findings, audit evidence or the original SharePoint
file. A later policy decision can retain termination events longer than three
source snapshots if compliance requires it.

## Import flow

```text
Excel → validate headers/types → create import_batch
      → insert typed facts + governed field values
      → validate counts/checksum → mark COMPLETED
      → evaluate business rules from persisted facts
```

An invalid file is marked `FAILED` or `COMPLETED_WITH_WARNINGS` with an error
message. Its transaction is rolled back, so it cannot block the next import.
Rule evaluation runs after commit and is never allowed to change a successful
import into a failed import.

## Migration implementation order

1. Apply the Alembic star-schema migration (`0013_star_schema`) to the runtime.
2. Add repository/service methods for batch lifecycle, typed facts and governed
   field values.
3. Update each source adapter to write the star facts directly.
4. Update reports and business rules to query facts instead of source JSON.
5. Add an Administration dry-run showing batches, row counts and cleanup scope.
6. Add a confirmed migration/retention action with automatic backup and a
   post-cleanup integrity check.
7. Run `VACUUM` only after the transaction and validation succeed. This is
   required because SQLite does not automatically shrink the file after
   `DELETE`.

For testing, Administration → Governance exposes **Rebuild star-schema testing
runtime**. It requires typing `REBUILD STAR TESTING RUNTIME`, creates a backup,
clears employee/import data and star facts, and preserves access-control data.
It does not publish to SharePoint. The action is a data reset plus schema
preparation; source adapters still need to be switched to write the new facts
in the next implementation step.

The existing JSON-oriented tables and compact pilot tables are intentionally
not part of this clean-start design. They can remain in the old branch for
reference, but must not be recreated in the new runtime schema.
