# IAM Automation Documentation Hub

This is the entry point for project documentation. Every active feature, bug,
work item and unresolved decision should be discoverable from here or from the
linked status registry.

## Control documents

- [Delivery status](./STATUS.md) — authoritative status of features, bugs and user stories.
- [Documentation architecture](./architecture/DOCUMENTATION_ARCHITECTURE.md) — folder rules, lifecycle and cross-reference conventions.
- [Current implementation plan](./work/2026-09-04-implementation-plan.md) — plan for the September 8 milestone.
- [Work tracking](./work_tracking/README.md) — backlog, decisions and bitacora.
- [Archive](./archive/README.md) — historical material retained for traceability.
- [User stories source](./users_history/source/users_history.md) — canonical editable stakeholder guide; generated deliverables are separated.

## Active work

- [Business Rules Framework](./features/2026-09-business-rules-framework.md) — active foundation; see the [current rules engine behavior](./architecture/RULES_ENGINE.md). The in-app Business Rules Help page is available at `/help/business-rules`.
- [Ingestion Engine design](./architecture/INGESTION_ENGINE_ARCHITECTURE.md) — design baseline for the source-agnostic ingestion boundary; implementation is tracked in [the Ingestion Engine work plan](./work/2026-09-22-ingestion-engine-work-plan.md).
- [Refresh alert](./bugs/2026-09-refresh-alert.md) — confirmed defect, fix pending.

## Requirement and decision sources

- [Meeting notes — 2026-09-04](./meetings/2026-09-04/notes.md)
- [Meeting backlog — 2026-09-04](./meetings/2026-09-04/backlog.md)
- [Next UAT decisions](./uat/UAT_NEXT_MEETING_DECISIONS.md)
- [Current architecture](../ARCHITECTURE.md)

## Folder map

| Folder | Purpose |
|---|---|
| `bugs/` | Confirmed defects, reproduction, impact, fix plan and verification. |
| `features/` | Feature briefs, user stories, acceptance criteria and implementation status. |
| `work/` | Plans, milestones, execution slices and handoff checklists. |
| `pending/` | Unresolved decisions, external dependencies and blocked items. |
| `architecture/` | System and documentation architecture decisions. |
| `meetings/` | Immutable meeting notes and meeting-specific backlogs. |
| `work_tracking/` | Operational control center and chronological implementation record. |
| `archive/` | Superseded designs, historical meetings and legacy artifacts. |
| `uat/` | UAT scenarios, risks and business questions. |

Historical documents remain in their original locations so existing references
and evidence are not broken. New documents must use the structure above.
