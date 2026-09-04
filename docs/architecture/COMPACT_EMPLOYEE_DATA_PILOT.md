# Compact Employee Data Pilot

## Decision

The first experiment adds a relational **current-state projection** without
deleting the existing JSON evidence. `workers` remains the canonical identity;
`field_catalog` governs which fields are allowed in the compact layer and
`employee_field_values` stores one current value per employee, source and field.

```text
workers 1 ── * employee_field_values * ── 1 field_catalog
                    |
                    +── source_system / source_record_id / observed_at
```

## What is included

The pilot starts with identifiers, names, email/phone, status, dates and common
assignment fields. Unknown report columns are not copied into this layer. A
new report field is added deliberately by registering it in
`EmployeeFieldProjectionService.PILOT_FIELDS` and then assigning its catalog
metadata (type, sensitivity, reportable and rule-enabled).

The existing `ingestion_records`, source profiles, lineage and profile history
remain the evidence/audit layer for now. This makes the change reversible and
lets us compare row counts and disk usage before any retention cleanup.

## Import error behavior

An import transaction is isolated per request. Validation errors are shown to
the user and do not prevent a later import. Unexpected import errors are logged
and rendered as a safe retry message. Post-import rule evaluation is enrichment:
if it fails, the import remains completed and can be reviewed or evaluated
again later; it does not make the import page unusable.

## Trial checklist

1. Apply the migration on a copy or disposable runtime.
2. Import one valid file and confirm the batch completes.
3. Import one malformed/unsupported file and confirm a readable error appears.
4. Import the valid file again and confirm it is accepted.
5. Promote a staged record and inspect `field_catalog` and `employee_field_values`.
6. Compare SQLite size before/after; do not remove legacy JSON until the result
   is reviewed.

The same checks are available in `Administration → Governance → Migration
diagnostics`. A green `Verified` badge requires revision
`0012_compact_employee_fields` plus both pilot tables. The panel also shows
detected columns, indexes, governed-field count and current-value count.
