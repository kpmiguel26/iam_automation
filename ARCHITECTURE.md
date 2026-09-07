# Architecture

## Current Delivery Phase — Read-only Employee & Evidence Review

The current delivery phase is a read-only review increment. The application may
read the published runtime SQLite snapshot and display employee, source,
history, discrepancy, duplicate and audit evidence. It must not change the
canonical employee, merge workers, approve or apply employee changes, or
publish a new runtime or Access snapshot as part of this phase.

The repository contains write-capable workflow code from the broader target
architecture. Those paths are future-phase capabilities and are not part of
the current release acceptance criteria. Before production use, they must be
disabled, feature-gated, or exposed only in a separately approved writer
deployment.

## Corrected Decision

IAM Automation uses a single-writer approval workflow. There is no central API, server, VM, persistent service, or distributed coordinator in the current infrastructure.

Microsoft Access is treated as a versioned master snapshot published to SharePoint. It is not a live multi-user database edited directly through OneDrive.

## Conceptual Flow

1. The local PySide6 startup shell discovers and validates the OneDrive-synchronized SharePoint route.
2. The startup shell verifies the published Access database and published runtime SQLite snapshot.
3. The startup shell validates the runtime checksum and copies SQLite atomically to the ignored project-root `runtime.sqlite`.
4. The startup shell records workstation traceability and completes separate IAM account authentication.
5. A local Flask webapp starts on `127.0.0.1` with an ephemeral port and opens in the browser.
6. Authenticated users view employee profiles, engagements, source lineage, history, discrepancies and duplicate evidence.
7. Authorized users view read-only request, approval, notification and audit evidence where available.
8. Reports and evidence exports may be generated without modifying canonical employee records.
9. Source observations may be detected or staged for review, but they must not be promoted into or overwrite the canonical employee in this phase.
10. Employee changes, approvals, merges, Access updates and snapshot publication remain future-phase operations.

## Startup MVC Boundary

The startup shell is a local MVC component, not a central service. Its controller coordinates path discovery, environment validation, settings persistence, and identity handoff. The Qt view displays status and selection controls but does not inspect files directly. Flask defines the local WSGI application and Waitress serves it on loopback, avoiding the Flask development server while preserving a simple path to a future deployment configuration. `Open App` starts Flask and Waitress in an independent local process, opens the browser, closes the PySide6 window, and terminates the desktop launcher process.

For the current development and test phase, the preflight registers the current operating-system identity in the runtime SQLite and publishes it with backup/audit metadata. This removes setup friction across VDI, Windows, and macOS test machines. A strict approved-user hard gate is reserved for production hardening after the SharePoint/AD integration is available.

The startup gate rejects web URLs, unrelated local folders, missing Access or runtime SQLite snapshots, invalid SQLite integrity/checksum, unreadable files, and workspaces located inside OneDrive. Missing operational folders are created idempotently after both database files are found; database files are never created or replaced by this step.

## Python Package Organization

The package follows a pragmatic Screaming Architecture layout:

- `database/`: Access schema, initialization, and master-snapshot persistence boundary.
- `environment/`: SharePoint discovery, settings, and startup preflight use cases.
- `security/`: Windows identity and role authorization boundary.
- `change_management/`: request-driven create, update, deactivate, approval, and apply workflows.
- `governance/`: audit, checksums, locking, publication, and recovery controls.
- `interfaces/`: PySide6 desktop and loopback Flask presentation layers.
- `architecture/`: package-level composition and future architecture decisions.

The original flat modules remain as compatibility facades during migration so existing scripts and tests do not break. New application code should import from the business-oriented packages above.

Source ingestion now has an explicit incremental boundary. Shared ingestion
contracts, stable reads, deduplication and adapter dispatch live under
`application/ingestion/`; format-specific readers and normalizers live under
`source_adapters/`; relational source-fact persistence lives under
`infrastructure/sqlite/star_schema_writer.py`. See
[`docs/architecture/INGESTION_ARCHITECTURE.md`](docs/architecture/INGESTION_ARCHITECTURE.md)
for the implemented flow and remaining migration sequence.

## Current-Phase Non-Negotiable Boundary

Client applications must not:

- Modify the published Access database.
- Replace the Access snapshot.
- Publish Access master versions.
- Apply approved changes.
- Merge or update the canonical employee.
- Create or execute change-role submissions.
- Treat a request, approval or report view as permission to mutate data.

The current phase exposes no writer workflow as an accepted product capability.
Administrator/Writer batch processing and publication belong to the future
controlled-change phase and require separate scope approval.
