# Implementation Plan — September 4 to September 8, 2026

**Owner:** Miguel Fernandez  
**Target:** Tuesday 2026-09-08  
**Current branch baseline:** `production`  
**Release constraint:** preserve the Phase 1 read-only boundary

## Outcome

Deliver a documented, tested first increment of configurable Business Rules
and eliminate the delayed published-runtime refresh alert.

## Workstream A — Refresh alert (highest risk first)

1. Extract the dashboard freshness guard into shared authenticated layout code.
2. Keep `/workspace/status` as the authoritative checksum comparison endpoint.
3. Add a single modal/notification instance and polling lifecycle per browser tab.
4. Add tests for every authenticated page category and publication/sync delay.
5. Add publication progress states only if they can be implemented without
   weakening the publication controls.

**Exit criteria:** DB-001 and DB-002 tests pass; a changed snapshot produces an
alert while the user remains on any authenticated page.

## Workstream B — Rules foundation

1. Freeze the first rule vocabulary and status model.
2. Add migration/models for rules, field policies, alert definitions and
   findings.
3. Implement a safe allow-listed condition evaluator; do not evaluate Python,
   SQL or arbitrary user-provided code.
4. Add administrator CRUD with route/service authorization, optimistic version
   checks, disable semantics and append-only audit events.
5. Add the configuration pages and status filters.

**Exit criteria:** BR-001 and AL-001/AL-003 are implemented and tested; rule
versions are auditable and inactive rules are not evaluated.

## Workstream C — Initial rules

1. Adapt existing Thirty-Day Rehire logic behind the rule service.
2. Preserve explicit date/calendar semantics and surface missing evidence.
3. Add No-Rehire as a finding-only rule with a documented matching contract.
4. Apply field protection policies to import validation and review output.
5. Add import/search summaries and alert dashboard data.

**Exit criteria:** BR-002–BR-006 and AL-002/AL-004 have tests, but no rule can
approve, merge, mutate canonical employees or provision downstream systems.

## Sequence and checkpoints

| Date | Checkpoint | Evidence |
|---|---|---|
| Sep 4 | Documentation and status architecture complete | `docs/STATUS.md`, feature/bug/work/pending docs |
| Sep 5 | Refresh alert implementation and focused tests | DB-001/DB-002 test report |
| Sep 6 | Rules schema/evaluator/service | migration, services, unit tests |
| Sep 7 | Admin UI, import/search integration and UAT pass | screenshots/test report/audit evidence |
| Sep 8 | Demo and sign-off decision | completed stories and remaining pending list |

## Risks and controls

- Rule growth: constrain the first DSL to allow-listed simple conditions.
- Policy ambiguity: keep unresolved business choices in `pending/`; do not
  infer them from existing code.
- Scope drift: configuration and evaluation must not become writer workflow.
- SharePoint latency: show freshness/sync state and test retry/idempotency.

## Definition of done

Each story needs implementation, authorization behavior, tests, documentation,
linked evidence and a bitacora entry. The status registry must be updated in
the same change.
