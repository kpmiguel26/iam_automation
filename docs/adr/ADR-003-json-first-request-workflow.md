# ADR-003: JSON-First Request Workflow

## Status

Accepted for the temporary development and staffing-transition mode.

## Decision

Change requests are created, assigned, reviewed, approved, and rejected as JSON files in the synchronized SharePoint workspace:

```text
SharePoint/requests/pending/
SharePoint/requests/under_review/
SharePoint/requests/approved/
SharePoint/requests/rejected/
```

The local SQLite runtime is not the workflow source of truth for requests. It remains available for application identity, configuration, audit metadata, and the final controlled publication step.

## Super Operator Exception

`SUPER_OPERATOR` is a temporary, audited operational bridge. It may complete the application workflow, including self-approval during the staffing transition, when the action is recorded as `REQUEST_SELF_APPROVED_BREAK_GLASS`. It cannot publish or restore the runtime SQLite database.

Self-approval remains blocked for ordinary users, reviewers, application administrators, and master administrators.

## Publication Boundary

Approved JSON remains in SharePoint until a designated administrator performs the final publication workflow. That workflow will validate the approved request set, create a backup, update the local runtime SQLite, calculate a checksum, and publish the resulting snapshot explicitly.

## Consequences

- All workstations can observe the same pending and approved request files through their synchronized SharePoint folder.
- JSON file transitions must be atomic and must preserve the request ID.
- Invalid or conflicting files remain available for quarantine handling.
- SQLite request tables are retained temporarily for compatibility and migration support but are not authoritative for the web request workflow.
- The final SQLite publication remains a protected operation and is unavailable to `SUPER_OPERATOR`.
