# Architecture

## Corrected Decision

IAM Automation uses a single-writer approval workflow. There is no central API, server, VM, persistent service, or distributed coordinator in the current infrastructure.

Microsoft Access is treated as a versioned master snapshot published to SharePoint. It is not a live multi-user database edited directly through OneDrive.

## Conceptual Flow

1. Installed user applications identify the Windows user and validate roles.
2. Requesters create immutable JSON request files.
3. Request files are written to the SharePoint-synced `requests/pending` folder.
4. An authorized Administrator/Writer imports pending requests in batches.
5. Malformed or duplicate requests are quarantined.
6. Requests are reviewed, approved, rejected, or marked as conflict.
7. Approved requests are applied to a local Access copy outside OneDrive.
8. The batch process validates integrity and generates official Excel outputs.
9. A versioned Access snapshot and manifest are published to SharePoint.
10. Audit events and batch summaries are recorded.

## Non-Negotiable Boundary

Client applications must not:

- Modify the published Access database.
- Replace the Access snapshot.
- Publish master versions.
- Apply approved changes.
- Bypass approval.

Only Administrator/Writer roles can perform batch processing and publication.
