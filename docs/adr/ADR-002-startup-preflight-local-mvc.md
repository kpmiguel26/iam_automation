# ADR-002: Startup Preflight and Local MVC Shell

Date: 2026-07-22  
Status: Accepted

## Context

The application depends on an Access snapshot stored in a SharePoint library synchronized locally through OneDrive. The application must know the local synchronized route before it reads the database, validates the user, or opens the operational web interface.

The current infrastructure does not provide a central API, server, Windows Service, or transactional database engine.

## Decision

Use a local PySide6 startup shell as the first MVC view. The startup controller will:

1. Resolve the route from environment variables, user settings, configuration, known OneDrive locations, or manual folder selection.
2. Validate the SharePoint root, Access database, required folders, local workspace, and file readability.
3. Persist only local path settings outside SharePoint and the repository.
4. Validate the Windows user and approved roles.
5. Start a Flask webapp bound only to `127.0.0.1` on an ephemeral port.
6. Start Flask as an independent local process, open the browser, and terminate the PySide6 launcher.

The Qt view will not inspect files directly. The Flask application will not write directly to the published Access database.

## Consequences

Positive:

- Users receive an actionable startup diagnosis before reaching the workflow.
- SharePoint route resolution becomes explicit and testable.
- The web interface remains a future migration path without creating a central service now.
- Local settings avoid repeated manual path selection.

Tradeoffs:

- PySide6 and Flask become UI dependencies.
- The first deployment requires a locally synchronized OneDrive library.
- The final role matrix and business rules remain separate follow-up decisions.
