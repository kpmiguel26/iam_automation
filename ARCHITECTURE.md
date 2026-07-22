# Architecture

## Corrected Decision

IAM Automation uses a single-writer approval workflow. There is no central API, server, VM, persistent service, or distributed coordinator in the current infrastructure.

Microsoft Access is treated as a versioned master snapshot published to SharePoint. It is not a live multi-user database edited directly through OneDrive.

## Conceptual Flow

1. The local PySide6 startup shell discovers and validates the OneDrive-synchronized SharePoint route.
2. The startup shell verifies both the published Access database and published runtime SQLite snapshot.
3. The startup shell creates missing SharePoint folders, validates the runtime checksum, and copies SQLite atomically to the ignored project-root `runtime.sqlite`.
4. The startup shell persists the validated settings and validates the Windows user against the approved-user role list.
5. A local Flask webapp starts on `127.0.0.1` with an ephemeral port and opens in the browser.
6. Requesters create immutable change requests or approved local SQLite configuration changes.
7. Request files and published snapshots are written to the SharePoint-synced workspace through controlled operations.
8. An authorized Administrator/Writer imports pending requests in batches.
9. Malformed, duplicate, or stale changes are quarantined or rejected.
10. Requests are reviewed, approved, rejected, or marked as conflict.
11. Approved employee changes are applied to a local Access copy outside OneDrive.
12. The batch process validates integrity and generates official Excel outputs.
13. An authorized administrator can publish the local SQLite runtime snapshot after checksum validation, backup, and optimistic concurrency checks.
14. A versioned Access snapshot and audit events are recorded.

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

## Non-Negotiable Boundary

Client applications must not:

- Modify the published Access database.
- Replace the Access snapshot.
- Publish Access master versions.
- Apply approved changes.
- Bypass approval.

Only Administrator/Writer roles can perform Access batch processing and publication. They may also publish a runtime SQLite snapshot after backup, checksum, and optimistic concurrency validation.
