# Feature F-005/F-006 — Configurable Business Rules and Alerts

**Status:** Planned  
**Priority:** High  
**Target:** 2026-09-08  
**Source:** [Meeting notes](../meetings/2026-09-04/notes.md), [meeting backlog](../meetings/2026-09-04/backlog.md)

## Objective

Provide a controlled administration surface for simple business rules and
their alerts, while preserving the current read-only product boundary.
Administrators configure rules; imports and searches evaluate them and expose
findings. No rule may directly mutate a canonical employee or execute a
downstream provisioning decision in this increment.

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
| BR-002 | Configurable Thirty-Day Rehire | Planned | Configurable threshold/calendar/exception; evaluated during import; no automatic approval. |
| BR-003 | Configurable No-Rehire | Planned | Admin configuration, matching evidence, automatic finding; no silent enforcement. |
| BR-004 | Field protection configuration | Planned | Protected/master/modifiable fields are versioned and enforced during review/import validation. |
| BR-005 | Import validation engine | Planned | Evaluate active rules, return per-record results, persist evidence and audit summary. |
| BR-006 | Search validation engine | Planned | Evaluate applicable restrictions for searches and show warnings without changing data. |
| AL-001 | Alert definition page | Planned | Create/edit/disable definitions with role protection and audit. |
| AL-002 | Custom simple alert rules | Planned | Alert definitions reference allow-listed rule conditions, not executable code. |
| AL-003 | Severity levels | Planned | Support INFO, WARNING, ERROR and CRITICAL with deterministic display behavior. |
| AL-004 | Alert dashboard | Planned | Show active alerts, alerts triggered today and history with filters. |

## Delivery slices

1. Define schema, status vocabulary, rule condition DSL and migration.
2. Implement repository/service with versioning, audit and authorization.
3. Implement admin pages for rules, field policy and alert definitions.
4. Adapt existing rehire evaluation behind the rule service.
5. Add no-rehire as evidence/finding only until business ownership is approved.
6. Integrate import/search evaluation and dashboard views.
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
