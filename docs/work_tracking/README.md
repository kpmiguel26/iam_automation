# IAM Automation Work Tracking

This folder is the working control center for implementation planning and project traceability.

## Files

- [`CURRENT_PLAN.md`](./CURRENT_PLAN.md): active implementation plan and deliverables.
- [`BACKLOG.md`](./BACKLOG.md): remaining work, grouped by feature and priority.
- [`BITACORA.md`](./BITACORA.md): chronological record of implementation, tests, findings and follow-up actions.
- [`DECISIONS.md`](./DECISIONS.md): working decisions that affect architecture or delivery.

## Working Rules

1. Every new feature starts on a dedicated Git branch.
2. Every meaningful implementation step is recorded in `BITACORA.md`.
3. New findings are added to `BACKLOG.md` instead of being kept only in chat.
4. A task is marked complete only after implementation and relevant tests are recorded.
5. Production hardening decisions remain explicit and are not silently inferred from development behavior.

## Current Branch

`feature/admin-control-center`

## Current Baseline

The local preflight, runtime SQLite synchronization, separate application login, local Flask/Waitress process and initial admin control center are operational in development.
