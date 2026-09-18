# Feature F-005/F-006 — Configurable Business Rules and Alerts

**Status:** Active — foundation implemented; remaining governance and alert slices are planned
**Priority:** High  
**Target:** 2026-09-08  
**Source:** [Meeting notes](../meetings/2026-09-04/notes.md), [meeting backlog](../meetings/2026-09-04/backlog.md)

## Objective

Provide a controlled administration surface for simple business rules and
their alerts, while preserving the current read-only product boundary.
The application first persists imported data in SQLite and then evaluates
active rules against that persisted state. Phase one is advisory only: a rule
creates a finding/alert for the human in Overview and Dashboard; it never
rejects an import, quarantines a row, mutates a canonical employee or executes
a downstream provisioning decision.

## Initial domain model

- `BusinessRule`: stable ID, name, description, rule type, condition payload,
  active state, effective dates, version and audit metadata.
- `RuleFieldPolicy`: field name, source scope, protected/modifiable state and
  effective version.
- `AlertDefinition`: rule reference, severity (`INFO`, `WARNING`, `ERROR`,
  `CRITICAL`), recipient scope, active state and display route.
- `RuleFinding`: rule/version, source record or worker, outcome, evidence,
  created time and review status.

Rules must use an allow-listed condition vocabulary rather than arbitrary code
or executable expressions. Initial conditions should cover dates, equality,
presence/missing values, status and process/source type.

## User stories

| ID | Story | Status | Acceptance criteria |
|---|---|---|---|
| BR-001 | Business Rules management page | Planned | List, create, edit, disable; server-side authorization and audit. |
| BR-002 | Configurable Thirty-Day Rehire | Planned | Configurable threshold/calendar/exception; evaluated after import; alert only. |
| BR-003 | Configurable No-Rehire | Planned | Admin configuration, matching evidence, automatic finding; no silent enforcement. |
| BR-004 | Field protection configuration | Planned | Protected/master/modifiable fields are versioned and enforced during review/import validation. |
| BR-005 | Post-import rule evaluation engine | Planned | Evaluate active rules after SQLite persistence, return per-record findings, persist evidence and audit summary without changing import status. |
| BR-006 | Search validation engine | Planned | Evaluate applicable restrictions for searches and show warnings without changing data. |
| AL-001 | Alert definition page | Planned | Create/edit/disable definitions with role protection and audit. |
| AL-002 | Custom simple alert rules | Planned | Alert definitions reference allow-listed rule conditions, not executable code. |
| AL-003 | Severity levels | Planned | Support INFO, WARNING, ERROR and CRITICAL with deterministic display behavior. |
| AL-004 | Alert dashboard | Planned | Show active alerts, alerts triggered today and history with filters. |

## Delivery slices

1. Define schema, status vocabulary, rule condition DSL and migration.
2. Implement repository/service with versioning, audit and authorization.
3. Implement admin pages for rules, field policy and alert definitions.
4. Retire code-owned rehire evaluation; express any approved rehire policy as
   a user-created rule recipe with versioned calendar and evidence.
5. Add no-rehire as evidence/finding only until business ownership is approved.
6. Integrate post-import evaluation and Overview/Dashboard alert views; keep search as a read-only consumer of existing findings.
7. Add fixtures, regression tests and UAT evidence.

## Decisions still required

- Calendar days versus business days and the authoritative holiday calendar.
- No-rehire source, matching keys, owner and override process.
- Which fields are protected per source and whether a conflict blocks one field
  or the full record.
- Finding recipients, severity defaults, retention and resolution evidence.
- Whether administrator configuration is allowed in the read-only release or
  requires a separately approved configuration-writer capability.

See [pending decisions](../pending/2026-09-business-rules-decisions.md).
