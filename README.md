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
python run_app.py
python scripts/create_access_database.py "C:\\path\\to\\iam_automation.accdb"
python scripts/sync_runtime_database.py "C:\\path\\to\\OneDrive - Organization\\IAMAutomation"
python scripts/create_runtime_database.py --publish-root "C:\\path\\to\\OneDrive - Organization\\IAMAutomation"
python scripts/submit_change_request.py --pending-folder /tmp/iam_requests/pending --username DOMAIN\\user --entity-id E12345 --expected-record-version 4 --payload-json "{\"manager_id\":\"M100\"}" --reason "Manager reassignment"
python scripts/admin_import_pending_requests.py --requests-root /tmp/iam_requests --username DOMAIN\\admin
```

The desktop launcher first discovers and validates the local OneDrive-synchronized SharePoint path. It opens the local Flask webapp only after the environment and current user have passed validation. Flask is served by Waitress on `127.0.0.1` with an ephemeral port. The local UI components are a transitional client architecture and are not a centralized API or service.

Convenience launchers are available for both platforms:

Windows:

```bat
run_windows.bat
```

macOS:

```bash
./run.sh
```

Both launchers require Python 3.10 or newer, create or reuse `.venv`, upgrade the package tools, update the project dependencies, and start the desktop preflight shell.

During the current local development phase, the preflight registers the current VDI, Windows, or macOS identity in the runtime SQLite automatically. The default development role is `REQUESTER`; set `IAM_DEV_DEFAULT_ROLE=ADMINISTRATOR` when needed for testing. A strict approved-user gate remains a planned production hardening step.

The startup preflight validates the current Windows identity separately from the IAM Automation application login. Application accounts are stored in the runtime SQLite database with password hashes. Create the first application account with:

```text
python scripts/create_runtime_database.py --path runtime.sqlite --publish-root "C:\path\to\SharePoint" --app-username iam.admin --app-password "choose-a-password" --role ADMINISTRATOR
```

The web login never uses the Windows username as application credentials and never stores a plaintext password.

For an interactive bootstrap that keeps the password out of the command history, use `scripts/create_app_user.py` and enter the password when prompted.

To stop the local Flask/Waitress process cleanly, run:

```text
python scripts/stop_app.py
```

On Windows, `run_windows_hidden.vbs` starts the same launcher without displaying a console window. Keep `run_windows.bat` for setup diagnostics and troubleshooting.

The Access database initializer requires Windows with the Microsoft Access Database Engine and ODBC driver. On macOS, inspect the generated Access schema without creating a fake database file:

```bash
./.venv/bin/python scripts/create_access_database.py placeholder.accdb --show-schema
```

On Windows with the Access ODBC driver installed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Validate-IAMEnvironment.ps1
python scripts/experiment_01_access_connectivity.py "C:\Users\E385201\OneDrive - Kaiser Permanente\IAMAutomation\iam_automation.accdb"
```

The working SQLite copy is `runtime.sqlite` in the project root and is ignored by Git. It is refreshed from the published SharePoint snapshot at startup. An administrative publish requires an explicit `--publish` action and may include `--expected-checksum` to prevent overwriting a newer shared copy.

For macOS development, Browse may point to any local folder containing the Access file and the published runtime snapshot. Production deployments should use the local OneDrive-synchronized SharePoint folder.

## Key rule

SharePoint or OneDrive sync is not a database server. Client applications must not write directly to the published `.accdb`. Ordinary users submit immutable request files; an authorized Administrator/Writer applies approved requests in controlled batches and publishes versioned Access snapshots.
