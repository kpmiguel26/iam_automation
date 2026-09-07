# Write model architecture

**Status:** Target write model implemented in the ORM and SQLite migration `0015_source_separated_write_model`; source writers are the next implementation phase.

The ingestion refactor separates file formats from application orchestration.
The next step separates the write model so a report cannot accidentally own
another report's fields. Source rows remain evidence; `employee` is the
canonical identity created from stable identifiers.

## Star-schema alignment

The logical source-owned entities below are implemented as star-schema facts
and bridges, not as another mixed employee table:

| Logical responsibility | Star-schema object |
|---|---|
| Canonical employee | `dim_employee` |
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
`fact_worker_field` tables remain migration scaffolding only; new writes use
the typed source facts defined here.

The initial `dim_employee.employee_key` is a generated application UUID. Source
identifiers remain attributes in `bridge_employee_identifier`; they are never
used as the dimension primary key. A later migration may add an integer
warehouse key without changing source identifiers or the application UUID.

## Change-to-write mapping

This matrix is the implementation contract for the next writing phase:

| Requirement | Star-schema object | Operation | Owner | History and retention |
|---|---|---|---|---|
| Separate each report | `fact_accessnow_employee`, `fact_master_roster_employee`, `fact_roster_lock_assignment`, `fact_rsr_assignment` | Insert one immutable fact per source row and batch; assign `employee_key` only after approved identity resolution | The matching source writer | Source values are never updated; source batch retention is applied independently. |
| Link a report row to an employee | `bridge_employee_identifier` plus `employee_key` on each fact | Resolve strong IDs, then link; create only with a strong ID | `EmployeeIdentityService` | Every link keeps `source_record_id`, batch and validity dates. Ambiguous rows remain unlinked and reviewable. |
| Add source values without overwriting evidence | `fact_source_field_value` and typed source facts | Append a new observation; do not update a prior fact | Source-specific writer | Old observations remain immutable. The latest value is a derived read projection. |
| Maintain employee history | `fact_employee_field_history` and `employee_current` view | Append a new employee version when a governed field changes | Field owner writer; AccessNow for status | Keep the newest three employee versions per employee. Cleanup runs only after the new version and audit evidence commit. |
| Own employee status | `fact_employee_status_event` and `employee_current.status` | Append/supersede only from valid AccessNow events | `AccessNowStatusWriter` | Other sources may record their own status fields as evidence but cannot write the canonical status event. |
| Limit AccessNow terminations | AccessNow import policy plus `import_batch.filtered_rows` | Insert active rows and only eligible inactive events | `AccessNowIngestionService` | Normal window starts January 1 of the current year; January uses a rolling three-month window ending on import date. |
| Add a new report safely | `dim_source`, `dim_field`, `source_field_mapping`, one new `fact_*` adapter | Register metadata and add an isolated reader/normalizer/validator/writer | New source owner | Existing facts and mappings remain unchanged; historical reprocessing is explicit. |

“Append only” applies to source values and employee history. A staged source
fact may receive its one-time `employee_key` link during approval; its report
values remain immutable. The
`employee_current` view (or a materialized projection maintained in one
transaction) may change because it is derived from the newest accepted facts;
that does not mutate historical evidence.

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

`dim_employee.employee_key` is an internal UUID and is the only canonical employee
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
the status fact. The old `workers.status` column is outside the target model and
will be removed after consumers move to `employee_current`.

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

## Administrator field assignment

The administrator should choose which source fields participate in employee
identity, canonical projections, reports and rules. The administrator should
not create physical columns or select arbitrary database tables from the UI.
Physical schema changes remain versioned migrations; administrative choices are
versioned metadata applied by the writer.

Use one governed `dim_field` catalog and these metadata relations:

```text
dim_field
  ├── source_field_mapping
  ├── field_ownership
  └── employee_identity_rule
```

### `dim_field`

The catalog describes the business meaning of a field: `field_key`, label,
data type, sensitivity, reportable flag, rule-enabled flag, target entity,
target attribute and lifecycle status. It is the single catalog; the current
duplicate `field_catalog` table should be consolidated into it during the ORM
migration.

### `source_field_mapping`

This relation maps a source column to a governed field without changing the
source fact table:

| Field | Purpose |
|---|---|
| `source_id`, `source_field_key` | Source report and normalized column name. |
| `field_id` | Governed semantic field in `dim_field`. |
| `target_kind` | `IDENTIFIER`, `EMPLOYEE_ATTRIBUTE`, `STATUS_EVENT`, `ASSIGNMENT`, or `SOURCE_ONLY`. |
| `transform_name` | Allowlisted normalization function; never arbitrary code. |
| `effective_from`, `effective_to`, `mapping_version` | Historical mapping control. |
| `active` | Whether new imports use the mapping. |

The same source field may remain source-only while a later mapping promotes it
to a canonical target. Existing observations are not silently rewritten.

### `field_ownership`

This relation enforces one writer for each canonical field. It stores the
canonical `field_id`, `owner_source_id`, write policy (`CREATE`, `UPDATE`,
`READ_ONLY`), effective dates and a locked flag. A field may have many source
observations, but only one active owner. `status` is permanently locked to
AccessNow in this policy; changing that owner requires a reviewed migration,
not an ordinary field-assignment action.

### `employee_identity_rule`

This relation controls which mapped fields can link or create an employee:

| Field | Purpose |
|---|---|
| `source_id`, `field_id` | Source and mapped identity field. |
| `identifier_type` | Value stored in `bridge_employee_identifier`. |
| `priority` | Order of exact matching across identifiers. |
| `match_mode` | Initially `EXACT_NORMALIZED`; fuzzy matching remains review-only. |
| `allow_employee_creation` | Strong identifiers only; names and email default to false. |
| `unique_scope` | Source/system scope for uniqueness. |
| `active`, effective dates | Versioned policy lifecycle. |

The initial rules are AccessNow employee ID and NUID, Master Roster employee
number/NUID/NPN, Roster Lock vendor plus employee ID, and RSR worker ID,
supplier reference or buyer reference. Manager/sponsor NUID and work-order ID
remain assignment references and cannot create an employee.

## Recommended operating model

Use a hybrid model:

- Keep frequently joined, typed attributes in `dim_employee` and typed source
  facts (`status`, dates, vendor, assignment and identity keys).
- Store newly discovered or low-use fields in `fact_source_field_value` keyed by
  `dim_field` until a migration promotes them to a typed column.
- Let administrators map, activate, deactivate and report on fields through
  metadata. Require review and audit for ownership or identity-rule changes.
- Apply a mapping version only to new imports by default. Offer an explicit,
  reviewable reprocess for historical batches.

This gives the administrator control over what is linked to an employee while
preserving star-schema joins, type safety for core facts, historical lineage
and a single writer for each canonical field.

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

For the current implementation year, the filter uses the UTC calendar year at
ingestion time (2026 in the current workspace). It must be configurable for
backfills and tests. The January exception is deliberate: a rolling three-month
window retains recent prior-year terminations long enough to evaluate the
30-day rehire policy.

- Import all valid AccessNow active rows.
- Import `TERMINATED` and `DEACTIVATED` rows only when their parsed effective
  date is in the active window: current calendar year outside January, or the
  previous three months during January.
- Exclude inactive rows outside that window from source write facts and status
  updates, while counting them as filtered rows on the batch.
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

1. **Completed:** add source-specific ORM models and migration
   `0015_source_separated_write_model`.
2. Add an `EmployeeIdentityService` that implements the strong-ID order and
   writes `employee_identifier` links.
3. Add `AccessNowStatusWriter` with the current-year termination policy and
   tests for active, current-year, prior-year and undated events.
4. Add append-only employee history with a transactional three-version cleanup.
5. Migrate AccessNow writes first, then Master Roster, Roster Lock and RSR.
6. Update readers to use `employee_current` and source-specific facts.
7. Backfill/validate counts and lineage on a disposable SQLite copy.
8. Retire mixed `ingestion_records`/profile writes only after all consumers and
   exports use the new tables.
