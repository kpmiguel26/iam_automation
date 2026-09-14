# Rules engine — current behavior

**Review date:** 2026-09-14
**Status:** active, advisory-only / phase 1
**Primary code:** `iam_automation/application/business_rule_service.py`

This document describes the current rules engine based on the implementation
and its tests. Business architecture documents may include future capabilities;
those are marked explicitly when they are not implemented yet.

## 1. Purpose and phase-one boundary

The engine reviews evidence from imported reports and creates findings for
human review. It does not make or execute changes in authoritative systems.

A rule match:

- does not cancel the import;
- does not reject or approve a hire;
- does not modify a `Worker`, canonical employee or permission;
- does not write back to AccessNow, RSR/Fieldglass, Roster Lock or Master Roster;
- does not publish changes to the shared workspace by itself.

Rule quarantine is a review surface. It must not be confused with the invalid
row quarantine produced by ingestion adapters.

## 2. Execution flow

```text
Source file/folder
        |
        v
BEFORE: normalized rows in memory
        |
        v
Source adapter
        |
        v
Import batch + source facts committed to SQLite
        |
        v
AFTER: persisted facts
        |
        v
rule_findings + fact_quarantine
        |
        +--> Overview / Dashboard
        +--> Administration / Quarantine
        +--> human review
```

`IngestionOrchestrator` runs rules in two phases. `RuleRegistry` discovers the
implementations in `application.rules`, sorts them by `key`, and runs only the
rules applicable to the current phase and source.

### BEFORE

`ConfiguredBusinessRulesBeforeImport` reads and normalizes the source file
before calling the adapter. It returns matches in the rule result; it cannot
create a finding yet because `record_id` and `batch_id` do not exist.

### AFTER

`ConfiguredBusinessRulesAfterImport` runs after the batch has been created:

1. links BEFORE matches to records in the batch;
2. evaluates active AFTER rules;
3. creates findings and their quarantine projection.

If a rule raises an exception, the error is returned in `RuleResult` and the
completed import is preserved for evaluation retry. The `blocking` field is
retained for compatibility and future policy, but it does not block imports in
phase one.

## 3. Sources and scope

Configured rules recognize these sources:

| Code | Source | Scope behavior |
|---|---|---|
| `ROSTER_LOCK` | Roster Lock | Filters records from this source. |
| `MASTER_ROSTER` | Master Roster | Filters records from this source. |
| `RSR_SUPPLIER_WORKER_DETAILS` | Fieldglass / RSR Supplier Worker Details | Filters records from this source. |
| `ACCESSNOW` | AccessNow | Evaluates the consolidated folder view. |
| `ALL` | All reports | Does not add a `source_system` filter. |

A simple rule is stored with `scope_json = {}` for `ALL`, or with
`{"source_system": "..."}` for a specific source. AFTER evaluation skips any
record whose `source_system` does not match the scope.

Composite conditions can reference fields from multiple sources. To resolve
them, the record must have a `matched_worker_id` and linked evidence from the
referenced sources. Without that relationship, the evaluator can only use the
current record's flat payload.

## 4. Persisted model

| Table | Responsibility |
|---|---|
| `business_rules` | Rule identity, name, description, status and current version. |
| `business_rule_versions` | Phase, scope, condition, severity and `context_version_id` for a version. |
| `rule_findings` | Technical record of each match: batch, record, worker, evidence and fingerprint. |
| `fact_quarantine` | Operational quarantine read model, enriched with source, field, observed value and status. |
| `rule_contexts` / `rule_context_versions` | Versioned global context for calendar, timezone, missing data and date boundaries. |
| `rule_calendars` / `rule_calendar_versions` / `rule_calendar_holidays` | Operating days and enabled holidays. |
| `dim_field` / `source_field_mapping` | Governed field catalog and source-to-field relationship. |

Each finding keeps a copy of its evidence in `evidence_json`, including the
`record_id`, source and payload reconstructed from source facts. After the
star-schema migration, JSON fields on valid records are cleared; the engine
reconstructs the payload from `fact_source_snapshot` and `fact_worker_field`.

Deduplication uses `SHA-256(rule_id + ":" + rule_version_id + ":" +
record_id)`. Reevaluating the same batch therefore does not create another
finding for the same rule version and record. A new rule version produces a
different fingerprint.

## 5. Operational lifecycle

### Rules

The interface and service currently support:

```text
DRAFT --Activate--> ACTIVE --Disable--> DISABLED
  |                    |
  +------ Test --------+
```

- Create: always starts as `DRAFT`, version 1.
- Test: works for `DRAFT` and active rules; it changes no state and creates no findings.
- Activate: changes the rule and its current version to `ACTIVE`.
- Disable: changes the rule and its current version to `DISABLED`; existing findings are preserved.
- Delete: removes the rule, versions, findings and `fact_quarantine` rows. This is destructive for operational evidence.

The schema is prepared for versioned rules, but no edit operation currently
creates version 2. The administration flow does not expose
`effective_from`/`effective_to` or editing of existing conditions.

### Findings

Review states are `OPEN -> ACKNOWLEDGED -> RESOLVED` and
`OPEN/ACKNOWLEDGED -> SUPPRESSED`.

`RESOLVED` and `SUPPRESSED` require a note. The update changes both
`rule_findings` and `fact_quarantine`, recording actor and timestamps. The web
route also writes an audit event for the status change.

## 6. Condition language

Conditions are JSON interpreted by an allow-list. They are never executed as
Python, SQL, templates or arbitrary callables.

### Simple/legacy form

```json
{
  "field": "email",
  "operator": "missing"
}
```

With a value:

```json
{
  "field": "assignment_status",
  "operator": "equals",
  "value": "TERMINATED"
}
```

### Explicit form

```json
{
  "left": {"kind": "field", "source": "MASTER_ROSTER", "field": "assignment_status"},
  "operator": "equals",
  "right": {"kind": "literal", "value": "TERMINATED"}
}
```

Supported operands are `literal` (fixed value), `field` (a source field, or
the current payload when no source is specified), and `derived` (a calculated
value). The only current derived function is `business_days_between`, which
requires two arguments.

Conditions can be grouped with `all`, `any` and `not`.

### Operators

The evaluator supports:

| Operator | Current semantics |
|---|---|
| `exists` | The key is present, even when its value is empty or `null`. |
| `missing` | The key does not exist, is `null` or is `""`. |
| `equals` / `not_equals` | Typed comparison; text and textual values are case-insensitive. |
| `contains` | Case-insensitive text containment; for lists, direct membership. |
| `in` | Current value matches one item in a list. |
| `greater_than` / `less_than` | Typed comparison. |
| `between` | Inclusive range; requires two boundaries. |
| `before` / `after` | Comparison of valid dates. |

The simple creation flow currently offers `exists`, `missing`, `equals`,
`not_equals`, `contains` and `in`. Numeric and date operators are available in
the evaluator and explicit editor.

Dates accept ISO and `MM/DD/YYYY` formats. Date rules do not match when a date
cannot be parsed.

### Business days

`business_days_between(start, end)` counts, by default, from the day after
`start` through `end`, including `end`, while excluding weekends and enabled
holidays. A reversed interval returns `-1`; the same date returns `0`, unless
both endpoints are explicitly included.

## 7. Configuration and governance

**Administration → Business rules → Rule configuration** can save local
versions of the default context; calendar, timezone, operating days and
holidays; and field metadata such as type, nullability, normalization and
`rule_enabled`.

When a rule is created, its version captures the current `context_version_id`.
This allows part of the creation context to be reconstructed later, but the
context currently stores `calendar_id`, not `calendar_version_id`. If the
calendar changes later, an older rule may read the current calendar version.
Complete reproducibility requires pinning the calendar version as well.

The Nager.Date holiday import is presented as a proposal in the interface, but
the current endpoint already persists a new calendar version with imported
rows enabled. Reviewing and saving the page creates another version. This must
be fixed or explicitly accepted before using the import as an approval flow.

The field catalog is populated from governed fields and headers observed in
reports. The service validates that a field is active and rule-enabled, but
the current validation does not enforce the type-specific operators in
`allowed_operators_json` when saving a condition.

## 8. Interface operation

1. Open **Administration → Business rules**.
2. Create a rule with the wizard: phase, source, condition, name and severity.
3. The rule is created as `DRAFT`.
4. Use **Test** to review matches against all local evidence or one batch.
5. Activate only after confirming scope, field, operator and values.
6. Review results in **Administration → Quarantine**.
7. Mark findings as `ACKNOWLEDGED`, `RESOLVED` or `SUPPRESSED`; resolving or suppressing requires a note.

Activating a rule from the interface reevaluates active AFTER rules against
historical batches. BEFORE rules are not retroprocessed; they start applying
on the next import.

Rule, context, calendar and metadata changes mark local publication as
pending. This distributes configuration through the controlled snapshot flow;
it does not write to an authoritative source.

## 9. Components and tests

| Component | File |
|---|---|
| Pipeline rule contract | `application/rules/base.py` |
| Discovery and execution | `application/rules/registry.py` |
| Configured-rule bridge | `application/rules/configured_business_rules.py` |
| Rule, finding and quarantine service | `application/business_rule_service.py` |
| DSL evaluator | `application/condition_evaluator.py` |
| Calendar and business days | `application/business_calendar.py` |
| Context and field configuration | `application/rule_configuration_service.py` |
| ORM persistence | `infrastructure/sqlite/orm.py` |
| Migrations | `database/alembic/versions/0011` and `0017`–`0020` |

Focused tests verified on 2026-09-14: `test_condition_evaluator`,
`test_business_rule_service`, `test_pipeline_rules` and
`test_rule_configuration`. The full suite result was `220 passed, 1 skipped`.
Coverage includes legacy and explicit DSL forms, groups, calendars,
source-fact reconstruction, source scope, BEFORE/AFTER behavior, idempotency,
side-effect-free preview and basic configuration authorization.

## 10. Review findings and pending decisions

| Priority | Finding | Impact |
|---|---|---|
| High | `RuleContextVersion.date_boundary` is loaded into `RuleCalendarSettings`, but `business_days_between` uses the `EXCLUSIVE_START_INCLUSIVE_END` default unless the operand includes `date_boundary`. | Selecting `INCLUSIVE_BOTH` in configuration currently does not change a derived condition unless the operand explicitly stores it. |
| High | A rule is linked to `context_version_id`, but that version stores only `default_calendar_id`; the evaluator reads the current version of that calendar. | Calendar changes can reinterpret historical findings from older rules. |
| Medium | `missing_data_behavior` and timezone are stored and versioned, but do not currently change general evaluation. | The screen can imply an applied policy while the values are still context metadata. |
| Medium | `exists` means “the key exists,” not “the key has a non-empty value.” | An `exists` rule can match a present but empty column; use `missing` to detect an absent value. |
| Medium | Rule versioning exists in the schema, but no edit flow creates new versions. | Changing a rule currently requires creating another rule or changing code. |
| Medium | Activating a rule reevaluates historical batches only for AFTER rules. | A newly created BEFORE rule does not generate historical findings automatically. |
| Medium | `delete_rule` removes findings and quarantine projections. | It must be treated as destructive and a retention policy is needed before production. |
| Medium | `import_holidays` immediately creates a new calendar version, although the UI presents imported holidays as a proposal to review and save. | An imported holiday can affect evaluation before explicit confirmation. |
| Low | Field-type metadata does not yet restrict operators when saving conditions. | A semantically unsuitable combination can be configured even if the evaluator accepts it. |
| Pending | There is no separate `AlertDefinition` or configurable recipient delivery. | Severity lives on the rule version and the current output is the UI/read model. |

These gaps do not invalidate the current advisory workflow, but they must be
fixed or explicitly accepted before presenting the engine as enforcement,
automated decision-making or a production control.

