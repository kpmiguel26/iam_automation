# IAM Automation Work Tracking

This folder is the working control center for implementation planning and project traceability. The wider documentation hub and cross-document status registry are in [`../README.md`](../README.md) and [`../STATUS.md`](../STATUS.md).

## Files

- [`CURRENT_PLAN.md`](./CURRENT_PLAN.md): active implementation plan and deliverables.
- [`BACKLOG.md`](./BACKLOG.md): remaining work, grouped by feature and priority.
- [`BITACORA.md`](./BITACORA.md): chronological record of implementation, tests, findings and follow-up actions.
- [`DECISIONS.md`](./DECISIONS.md): working decisions that affect architecture or delivery.
- [`../STATUS.md`](../STATUS.md): authoritative feature and user-story status registry.
- [`../work/2026-09-04-implementation-plan.md`](../work/2026-09-04-implementation-plan.md): active plan for the September 8 milestone.
- [`../bugs/`](../bugs/): confirmed defects and verification plans.
- [`../features/`](../features/): feature briefs and story acceptance criteria.
- [`../pending/`](../pending/): unresolved decisions and dependencies.

## Working Rules

1. Every new feature starts on a dedicated Git branch.
2. Every meaningful implementation step is recorded in `BITACORA.md`.
3. New findings are added to `BACKLOG.md` instead of being kept only in chat.
4. A task is marked complete only after implementation and relevant tests are recorded.
5. Production hardening decisions remain explicit and are not silently inferred from development behavior.
6. Every active feature or bug has one canonical document under `docs/features/` or `docs/bugs/`, with references recorded in `docs/STATUS.md`.

## Current Branch

`production` (documentation baseline; implementation work requires a dedicated feature/fix branch)

Release baseline: `production`

## Current Baseline

The local preflight, runtime SQLite synchronization, separate application login, local Flask/Waitress process, Admin Control Center, ingestion foundation and canonical worker history are operational in development. The active release phase is **Read-only Employee & Evidence Review**: employee profiles, source lineage, history, discrepancies, duplicate evidence, requests and audit evidence may be viewed or exported, while canonical mutation, approval, merge and publication are deferred. Generated runtime fixture data remains local and is excluded from Git.
