# IAM Automation Delivery Status

**Last reviewed:** 2026-09-04  
**Release baseline:** `production`  
**Current product phase:** Read-only Employee & Evidence Review  
**Next milestone:** Tuesday 2026-09-08

This is the status registry for documentation and planning. A feature is not
`Completed` until implementation, authorization behavior, tests and evidence
are linked.

## Status vocabulary

- `Completed` — implemented and verified with linked evidence.
- `Active` — currently being implemented or actively investigated.
- `Planned` — approved for work but implementation has not started.
- `Pending` — waiting for a stakeholder decision, external input or UAT.
- `Deferred` — intentionally outside the current release.
- `Blocked` — cannot proceed until a named dependency changes.

## Feature registry

| ID | Feature | Status | Stories | Evidence / next document |
|---|---|---|---|---|
| F-001 | Preflight and local runtime | Completed | Existing foundation stories | `startup.py`, runtime sync tests |
| F-002 | Authentication and authorization | Completed for development scope | Existing user/access stories | `identity.py`, admin tests; production hardening pending |
| F-003 | Admin control center and notifications | Completed for current scope | Existing admin stories | `admin_routes.py`, notification tests |
| F-004 | Source ingestion and employee evidence review | Active | Master Roster and source reconciliation stories | [Master Roster requirements](./work_tracking/2026-08-27_MASTER_ROSTER_REQUIREMENTS.md) |
| F-005 | Business Rules Framework | Active / foundation implemented | BR-001–BR-006 | [Architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md), [feature brief](./features/2026-09-business-rules-framework.md) |
| F-006 | Alert definition framework | Active / findings surface started | AL-001–AL-004 | [Architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md), [feature brief](./features/2026-09-business-rules-framework.md) |
| F-007 | Database publication and workspace refresh | Active investigation | DB-001–DB-003 | [Bug record](./bugs/2026-09-refresh-alert.md) |
| F-008 | Canonical mutation, approval and publication writer | Deferred | Future controlled-change stories | [Architecture boundary](../ARCHITECTURE.md) |
| F-009 | Compact employee current-state projection pilot | Active / pilot | DATA-001–DATA-003 | [Pilot architecture](./architecture/COMPACT_EMPLOYEE_DATA_PILOT.md) |

## User story registry

| ID range | State | Summary | Source |
|---|---|---|---|
| BR-001 | Active / first CRUD | Rules administration UI, validation and authorization | [Business Rules architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md) |
| BR-002–BR-004 | Planned | Rehire/no-rehire, calendars and field governance | [Architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md) |
| BR-005 | Active / foundation | Post-import evaluator and durable findings; no import blocking | [Business Rules architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md) |
| BR-006 | Planned | Read-only consumers of existing findings | [Business Rules brief](./features/2026-09-business-rules-framework.md) |
| AL-001–AL-003 | Planned | Alert administration, conditions and severity | [Business Rules brief](./features/2026-09-business-rules-framework.md) |
| AL-004 | Active / findings center | Open and critical post-import findings in Overview/Dashboard plus operational disposition center | [Business Rules architecture](./architecture/BUSINESS_RULES_ARCHITECTURE.md) |
| DB-001 | Active investigation | Fix missing refresh notification | [Refresh alert bug](./bugs/2026-09-refresh-alert.md) |
| DATA-001–DATA-003 | Active / pilot | Governed field catalog, compact employee values, resilient retryable imports | [Pilot architecture](./architecture/COMPACT_EMPLOYEE_DATA_PILOT.md) |
| DB-002–DB-003 | Planned | Global polling and publication progress | [Refresh alert bug](./bugs/2026-09-refresh-alert.md) |
| Master Roster read-only stories | Mixed | Staging/import completed; matching, comparison and conflict views pending | [Requirements](./work_tracking/2026-08-27_MASTER_ROSTER_REQUIREMENTS.md) |
| Change-role submission stories | Deferred | Not part of current read-only release | [Scope decision](./work_tracking/DECISIONS.md) |

## Completed baseline

The current baseline includes preflight, local SQLite synchronization, login,
role-aware administration, notifications, audit evidence, source staging,
worker history, duplicate evidence and read-only exports. The full regression
suite was recorded at 99 tests after the Windows ingestion merge; later work
also added duplicate-report and reconciliation increments.

## Release gate

Business Rules and refresh-alert work must not silently reopen the deferred
writer scope. If a rule would mutate canonical workers, approve a request,
merge identities or publish a business change, it requires a new scope decision.
