# Write model architecture

**Status:** Base design for the next implementation phase.

The ingestion refactor separates file formats from application orchestration.
The next step separates the write model so a report cannot accidentally own
another report's fields. Source rows remain evidence; `employee` is the
canonical identity created from stable identifiers.

## Star-schema alignment

The logical source-owned entities below are implemented as star-schema facts
and bridges, not as another mixed employee table:

| Logical responsibility | Star-schema object |
|---|---|
| Canonical employee | `dim_employee` (the current `workers` dimension during migration) |
| AccessNow source row | `fact_accessnow_employee` |
| Master Roster source row | `fact_master_roster_employee` |
| Roster Lock source row | `fact_roster_lock_assignment` |
| RSR source row | `fact_rsr_assignment` |
| AccessNow status event | `fact_employee_status_event` with `source_system = 'ACCESSNOW'` |
| Source identity links | `bridge_employee_identifier` |
| Unmapped governed fields | `fact_source_field_value` keyed by `dim_field` |

Every source fact carries `employee_key` when linked, `source_key`, `batch_id`,
`source_id`, `observed_date_key` and source-row lineage. `dim_source`,
`dim_date`, `dim_vendor`, `dim_field` and an optional `dim_status` remain shared
dimensions. The current generic `fact_source_snapshot` and
`fact_worker_field` tables are transitional compatibility facts; new writes
should move to typed source facts while preserving their lineage.

The internal UUID used today as `worker_id` can serve as the initial textual
`dim_employee.employee_key` to avoid breaking existing foreign keys. Source
identifiers remain attributes in `bridge_employee_identifier`; they are never
used as the dimension primary key. A later migration may add an integer
warehouse key without changing source identifiers or the application UUID.

## Core entities

```text
employee
  ├── employee_status              (owned only by AccessNow)
  ├── employee_identifier          (all source identity links)
  ├── employee_accessnow           (AccessNow report projection)
  ├── employee_master_roster       (Master Roster projection)
  ├── employee_roster_lock         (Roster Lock projection)
  └── employee_rsr                 (RSR / Fieldglass projection)
```

`employee.employee_id` is an internal UUID and is the only canonical employee
primary key. It is assigned once and never replaced when a worker changes
vendor, assignment or source identifier. Source identifiers are unique within
their source and are stored as values, not as the primary key of `employee`.

### `dim_employee` (logical `employee`)

This table contains fields that describe the canonical person and do not belong
to one report:

| Field | Rule |
|---|---|
| `employee_id` | Internal UUID primary key. |
| `first_name`, `last_name`, `display_name` | Canonical display values, populated only by the approved identity policy. |
| `canonical_email` | Canonical email used for safe fallback matching. |
| `created_at_utc`, `updated_at_utc` | Technical audit timestamps. |
| `record_version` | Optimistic concurrency value. |
| `superseded_by_employee_id` | Duplicate-merge link; source rows are never deleted. |

`status` is intentionally not written by the other report facts. The read-model
view `employee_current` exposes the latest AccessNow status event beside the
employee columns for existing screens.

### `fact_employee_status_event`

This temporal fact is the authoritative status relation:

| Field | Rule |
|---|---|
| `employee_key` | Foreign key to `dim_employee`; multiple events are retained. |
| `status` | AccessNow's normalized value (`ACTIVE`, `DEACTIVATED`, `TERMINATED`, or a reviewed unknown). |
| `source_record_id` | Foreign key to the AccessNow fact that supplied it. |
| `effective_date` | Business termination/deactivation date when supplied. |
| `observed_at_utc` | Time the source was imported. |
| `owner_source_system` | `CHECK (owner_source_system = 'ACCESSNOW')`; this fact has no other writer. |
| `updated_at_utc` | Technical audit timestamp. |

Only `AccessNowStatusWriter` may append or supersede this fact. Master Roster, Roster
Lock and RSR write their own tables and may never update or infer
the status fact. A compatibility migration can keep `workers.status` as a
read-only projection until all consumers use `employee_current`.

### `bridge_employee_identifier` (logical `employee_identifier`)

This table gives identity resolution one consistent link point:

| Field | Rule |
|---|---|
| `employee_identifier_id` | Internal UUID primary key. |
| `employee_id` | Canonical employee foreign key. |
| `source_system` | Source owner of the identifier. |
| `identifier_type` | Stable type such as `ACCESSNOW_EMPLOYEE_ID`, `ACCESSNOW_NUID`, `MASTER_EMPLOYEE_NUMBER`, `MASTER_NUID`, `MASTER_NPN`, `VENDOR_EMPLOYEE_ID`, `RSR_WORKER_ID`, or `BUYER_REFERENCE`. |
| `identifier_value`, `normalized_value` | Original and comparison forms. |
| `source_record_id`, `valid_from_utc`, `valid_to_utc`, `active` | Lineage and lifecycle. |

The uniqueness constraint is `(source_system, identifier_type,
normalized_value)`. Manager NUID, sponsor NUID and work-order IDs are
assignment references; they are not employee identity keys.

## Source-specific write facts

Each table has its own source record UUID, `batch_id`, `source_record_key`,
`source_file`, `source_checksum`, `row_number`, `observed_at_utc` and nullable
`employee_key`. The nullable link allows a row to be staged and reviewed before
identity resolution.

### `fact_accessnow_employee` (logical `employee_accessnow`)

Owns `accessnow_employee_id`, `accessnow_nuid`, AccessNow names/email,
vendor/job fields, manager and sponsor references, `accessnow_status` and
termination/deactivation dates. Its valid row is the only input to
`employee_status`; the table itself remains immutable evidence per batch.

Identity keys, in order of strength, are:

1. `accessnow_employee_id`;
2. `accessnow_nuid`;
3. canonical email as a reviewed fallback.

### `fact_master_roster_employee` (logical `employee_master_roster`)

Owns `employee_number`, `nuid_login_id`, `npn_login_id`, names, assignment
metadata and source dates. Its identity keys are `employee_number`, `nuid_login_id`
and `npn_login_id`. It never writes status.

### `fact_roster_lock_assignment` (logical `employee_roster_lock`)

Owns the vendor Roster Lock row, including `vendor_name`,
`vendor_employee_id`, names, email, assignment and lifecycle dates. Its stable
identity key is `(vendor_name, vendor_employee_id)`. It never writes status.

### `fact_rsr_assignment` (logical `employee_rsr`)

Owns Fieldglass/RSR values such as `worker_id`, `supplier_reference`,
`buyer_reference`, `work_order_id`, supplier, worker, role, status and dates.
`worker_id` is the preferred RSR identifier; `supplier_reference` and
`buyer_reference` remain source-scoped alternatives. It never writes status.

The source tables may have typed columns for fields used in joins and reports;
unmapped columns remain in a governed `source_field_value` extension table
linked to the source record. This avoids recreating one mixed JSON table while
preserving new report columns.

## Employee creation and linking

```text
source row staged
  → resolve identifiers in employee_identifier
  → one match: link source row to employee
  → no match with a strong identifier: create employee UUID and link it
  → multiple matches: quarantine as AMBIGUOUS; never create a duplicate
  → no reliable identifier: keep staged and request review
```

Names and email can support matching, but they cannot create a new employee by
themselves. A new employee must have at least one strong source identifier.
Every link records the source row and batch so an identity decision is
auditable.

## AccessNow status and termination policy

AccessNow is the final owner of employee status. A valid AccessNow row may set
`ACTIVE`, `DEACTIVATED` or `TERMINATED`; other report writers do not update the
status relation. If a current-year AccessNow event is ambiguous or has no
usable effective date, the row is quarantined/reviewed and the last accepted
status is preserved.

For the current implementation year, the filter is the UTC calendar year at
ingestion time (2026 in the current workspace). It must be configurable for
backfills and tests:

- Import all valid AccessNow active rows.
- Import `TERMINATED` and `DEACTIVATED` rows only when their parsed effective
  date is in the configured current year.
- Exclude prior-year inactive rows from source write tables and status updates.
- Quarantine inactive rows with a missing or unparseable effective date rather
  than changing status without evidence.
- Record the filtered count on the import batch so the operator can distinguish
  “not applicable this year” from a missing report.

The filter applies to inactive events only. An active AccessNow row remains
eligible to establish or update the current status because AccessNow is the
authoritative status source.

## Transaction boundary

One source import writes its batch metadata, source-specific rows, identifier
links and source facts in one SQLite transaction. Status updates occur in the
same transaction only when the source is AccessNow and the row passes the year
filter. Rule evaluation, notifications and approved canonical promotion run
after commit. A failed status update rolls back the source batch, so a partial
AccessNow import cannot leave `employee` and its status relation inconsistent.

## Implementation order

1. Add source-specific ORM models and migrations while retaining compatibility
   reads from the current tables.
2. Add an `EmployeeIdentityService` that implements the strong-ID order and
   writes `employee_identifier` links.
3. Add `AccessNowStatusWriter` with the current-year termination policy and
   tests for active, current-year, prior-year and undated events.
4. Migrate AccessNow writes first, then Master Roster, Roster Lock and RSR.
5. Update readers to use `employee_current` and source-specific tables.
6. Backfill/validate counts and lineage on a disposable SQLite copy.
7. Retire mixed `ingestion_records`/profile writes only after all consumers and
   exports use the new tables.
