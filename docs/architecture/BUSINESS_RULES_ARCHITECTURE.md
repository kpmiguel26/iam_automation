# Business Rules and Alert Architecture

**Status:** Active design / phase-one implementation  
**Source:** [September 4 meeting notes](../meetings/2026-09-04/notes.md) and [feature brief](../features/2026-09-business-rules-framework.md)

## Phase-one boundary

The ingestion layer reads and normalizes source data, then stages and persists
it in SQLite. Business rules query that staged evidence in `BEFORE` and query
committed facts in `AFTER`. The evaluator creates durable `RuleFinding` records
and advisory alerts; it does not parse a source file, select a source adapter,
reject the file, quarantine a row, change an employee, approve a request or
publish downstream changes.

```text
Source adapter / future ingestion engine -> SQLite staging -> BEFORE query
                                                        -> AFTER evaluation -> findings
                                                                                |-> Overview
                                                                                |-> Dashboard
                                                                                |-> human review
```

An evaluator failure is observable and retriable, but cannot turn a successful
import into a failed import.

## Engine boundary contract

The shared hand-off is defined in
`application/ingestion/contracts.py`. It is intentionally smaller than either
engine:

```python
@dataclass(frozen=True)
class IngestionBatch:
    batch_id: str
    source_id: str
    status: str
    records: tuple[NormalizedRecord, ...]
    field_mappings: tuple[FieldMapping, ...]
    metadata: BatchMetadata

@dataclass(frozen=True)
class NormalizedRecord:
    record_id: str
    source_id: str
    fields: dict[str, Any]
    metadata: RecordMetadata
```

The ingestion side produces the batch, normalized records and governed field
mappings. The Rules Engine consumes `batch_id`, normalized records and typed
metadata. Batch and record metadata are closed dataclasses; they are not an
arbitrary key/value bag. The contract contains no file path, report label,
reader, normalizer, adapter result or promotion behavior.

The current `SqliteEvidenceRepository` materializes this contract from the
existing tables as a compatibility bridge. New rule versions persist stable
`source_id` and `field_id` values, while historical versions may still carry
legacy source labels and field keys. The Rules Engine resolves those legacy
values only at its catalog boundary; this compatibility path does not enter
the hand-off and does not move source-specific logic into the rules domain.

The work is intentionally sequenced as:

1. Contract stabilization: `dim_source`, `dim_field`,
   `source_field_mapping`, `import_batches` and `ingestion_records`.
2. Rules Engine: consume the generic contract and remain file/adapter agnostic.
3. Ingestion Engine: later own discovery, adapters, mapping UI, normalization
   and staging.

Rule configuration and findings are local SQLite changes until the existing
controlled publication workflow publishes the runtime snapshot. They must not
be interpreted as an external workspace refresh.

## Proposed registry

- `BusinessRule`: stable identity, name, description, type and lifecycle.
- `BusinessRuleVersion`: immutable condition/scope/severity payload and audit.
- `CalendarDefinition` / `Holiday`: reusable calendars and named dates.
- `ReferenceSet`: no-rehire people, emails, identifiers and effective dates.
- `FieldCatalog` / `FieldPolicy`: field types, source mappings and governance.
- `ComparisonDefinition`: report-to-report or source-to-canonical comparison.
- `RuleFinding`: rule/version, batch/record/worker, evidence, severity and
  human resolution state.
- `AlertDefinition` / `AlertInstance`: delivery and display policy on findings.

The first implementation introduces rule/version/finding tables and an
allow-listed evaluator. Calendars, reference sets, field policies,
comparisons and administration UI follow as subsequent slices over this
registry boundary.

## Rule configuration context

The first context slice is administered at `/admin/business-rules/config` and
changes only local rule metadata. It provides:

- a default time zone, missing-evidence behavior and date-boundary convention;
- versioned operating calendars with selected weekdays and dated holidays;
- governed field metadata, including data type, nullability, normalization and
whether the field can be used by rules.

The configuration page can import a public-holiday proposal by country and
year from Nager.Date. Imported dates are displayed as table rows with an
administrator-controlled enabled switch. The current import endpoint already
persists a new local calendar version; saving the switches creates another
version. Nager.Date exposes public, bank, authority, optional and observance
types, so the application must still distinguish public holidays from the
organization's actual operating schedule. A failed import leaves the last
existing local calendar unchanged.

The existing `dim_field` and `source_field_mapping` tables remain the field
catalog and lineage boundary. The configuration page updates field metadata;
it does not change source mappings or source evidence. Raw-field type detection
can suggest a type, but the configured type controls the future operand and
operator vocabulary.

Calendar and context saves create a new version. Each newly created rule
version stores the current context version, and each context version stores the
exact calendar version selected at that time. Later calendar changes create new
versions and cannot affect older rule evaluations; see the [current rules
engine behavior](./RULES_ENGINE.md).
The configurable 30-business-day rehire threshold belongs to the rule
condition (`right operand = 30`); the calendar determines which dates count as
business days.

## Condition contract

Rules use JSON interpreted by a server-owned vocabulary. Existing rules retain
the compact `field/operator/value` shape. New composite rules use explicit
operands, for example:

```json
{
  "all": [
    {"left": {"kind": "field", "source": "ACCESSNOW", "field": "accessnow_status"}, "operator": "in", "right": {"kind": "literal", "value": ["TERMINATED", "DEACTIVATED"]}},
    {"left": {"kind": "derived", "function": "business_days_between", "arguments": [
      {"kind": "field", "source": "ACCESSNOW", "field": "termination_date"},
      {"kind": "field", "source": "ROSTER_LOCK", "field": "onboarding_date"}
    ]}, "operator": "between", "right": {"kind": "literal", "value": [0, 30]}}
  ]
}
```

The current allow-list includes `exists`, `missing`, `equals`, `not_equals`,
`contains`, `in`, numeric/date comparisons, `between`, and the derived
`business_days_between` function. Conditions compose with `all`, `any` and
`not`. User input is never evaluated as Python, SQL or arbitrary code. Cross-
source matching remains a separate context concern; the condition only reads
the matched source payloads it receives.

## Guided rule naming

Rules created from the administration wizard use a consistent display name:

```text
<EXECUTION_PHASE> - <REPORT_CODE> - <NUMBER> - <FIELD_KEY> - <DESCRIPTIVE_NAME>
```

For example: `AFTER - RL - 001 - email - email missing`. The phase, report and
affected field come from governed selections. The report code is derived from
the initials of the report label supplied by the source catalog, so the naming
convention does not maintain a hard-coded list of report codes. The
administrator supplies the rule number and a short descriptive name. The
guided-builder frontend formats the number to three digits and assembles the
final name live before submission. The backend persists that display name as
submitted, while the reviewer message remains separate optional text.

## User experience and status

Overview shows open and critical finding counts. Dashboard shows latest
findings, severity and context with a clear “post-import, advisory” label.
Current findings can be acknowledged, resolved or suppressed from
Administration / Quarantine, with actor, timestamp and reason.

Rule lifecycle: `DRAFT -> ACTIVE -> DISABLED`. Finding lifecycle:
`OPEN -> ACKNOWLEDGED -> RESOLVED`, with `SUPPRESSED` requiring an authorized
reason. `docs/STATUS.md` remains the single source of current delivery status.
