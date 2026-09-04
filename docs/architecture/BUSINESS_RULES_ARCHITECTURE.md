# Business Rules and Alert Architecture

**Status:** Active design / phase-one implementation  
**Source:** [September 4 meeting notes](../meetings/2026-09-04/notes.md) and [feature brief](../features/2026-09-business-rules-framework.md)

## Phase-one boundary

The import pipeline reads, normalizes, stages and persists source data in
SQLite. Business rules execute only after that transaction has committed. The
evaluator creates durable `RuleFinding` records and advisory alerts; it does
not reject the file, quarantine a row, change an employee, approve a request or
publish downstream changes.

```text
Source file -> import/stage -> SQLite commit -> rule evaluation -> findings
                                                        |-> Overview
                                                        |-> Dashboard
                                                        |-> human review
```

An evaluator failure is observable and retriable, but cannot turn a successful
import into a failed import.

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

## Condition contract

Rules use JSON interpreted by a server-owned vocabulary. Initial operators are
`exists`, `missing`, `equals`, `not_equals` and `in`, composed with `all` and
`any`. User input is never evaluated as Python, SQL or arbitrary code. Future
date, holiday, reference-set and comparison operators must be separately
allow-listed and versioned.

## User experience and status

Overview shows open and critical finding counts. Dashboard shows latest
findings, severity and context with a clear “post-import, advisory” label. A
future Findings work area can acknowledge, resolve or suppress findings with
actor, timestamp and reason.

Rule lifecycle: `DRAFT -> ACTIVE -> DISABLED`. Finding lifecycle:
`OPEN -> ACKNOWLEDGED -> RESOLVED`, with `SUPPRESSED` requiring an authorized
reason. `docs/STATUS.md` remains the single source of current delivery status.
