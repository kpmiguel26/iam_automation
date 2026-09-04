# Architecture

## Decision pending

The recommended production architecture is not final. The POC tests must decide whether Access is safe enough, and whether writes must be restricted to a single workstation or service.

## POC architecture

1. SharePoint repository synced locally through OneDrive stores the published Access database, backups, audit exports, templates, and configuration.
2. Local workspace under `%LOCALAPPDATA%\IAMAutomation\workspace` stores temporary working copies.
3. Data access coordinator owns all database operations.
4. Application lock prevents simultaneous write operations at the app level.
5. Optimistic concurrency checks prevent lost updates at the record level.
6. Audit JSONL files are append-only and can record failed operations even when database writes fail.

## Architecture options under evaluation

- Direct Access from OneDrive path: simplest, highest conflict risk.
- Local working copy with controlled publication: safer, still requires lock and stale-copy checks.
- Single-writer workstation or service: safest Access-era option if multiple users need the app.

See [docs/14_recommended_architecture.md](docs/14_recommended_architecture.md).
