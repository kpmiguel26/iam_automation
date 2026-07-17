# IAM Automation POC

This repository is the feasibility proof of concept for an internal IAM and employee-data automation application.

The current milestone is not the full application. The corrected architecture uses a single-writer approval workflow. Microsoft Access is treated as a versioned master snapshot published to SharePoint, not as a live multi-user database edited directly through OneDrive.

## Current scope

- Validate local OneDrive-synced SharePoint paths.
- Validate the Windows user against an approved-user list.
- Allow requester clients to create immutable JSON change request files.
- Import pending requests only through an Administrator/Writer batch workflow.
- Reject duplicate `request_id` values through idempotency tracking.
- Quarantine malformed or suspicious request files.
- Keep Access master updates restricted to the single-writer batch process.
- Create backups, audit events, versioned snapshots, and reconciliation reports during administrator processing.

## First commands

```bash
python -m pytest
python scripts/validate_environment.py --config config/sample_config.toml
python scripts/submit_change_request.py --pending-folder /tmp/iam_requests/pending --username DOMAIN\\user --entity-id E12345 --expected-record-version 4 --payload-json "{\"manager_id\":\"M100\"}" --reason "Manager reassignment"
python scripts/admin_import_pending_requests.py --requests-root /tmp/iam_requests --username DOMAIN\\admin
```

On Windows with the Access ODBC driver installed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Validate-IAMEnvironment.ps1
python scripts/experiment_01_access_connectivity.py "C:\Users\E385201\OneDrive - Kaiser Permanente\IAMAutomation\iam_automation.accdb"
```

## Key rule

SharePoint or OneDrive sync is not a database server. Client applications must not write directly to the published `.accdb`. Ordinary users submit immutable request files; an authorized Administrator/Writer applies approved requests in controlled batches and publishes versioned Access snapshots.
