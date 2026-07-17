# IAM Automation POC

This repository is the feasibility proof of concept for an internal IAM and employee-data automation application.

The current milestone is not the full application. The goal is to prove whether Microsoft Access can be used safely when the published `.accdb` lives in a SharePoint document library synchronized locally through OneDrive.

## Current scope

- Validate local OneDrive-synced SharePoint paths.
- Keep a local workspace outside OneDrive for working copies.
- Validate the Windows user against an approved-user list.
- Coordinate writes through a single data access coordinator.
- Create an application-level lock before writes.
- Create backups before publication.
- Write append-only audit events.
- Run POC experiments for Access connectivity, locking, optimistic concurrency, and SQLite comparison.

## First commands

```bash
python -m pytest
python scripts/validate_environment.py --config config/sample_config.toml
python scripts/experiment_04_application_locking.py /tmp/iam_automation.lock.json
python scripts/experiment_05_optimistic_concurrency_sqlite.py /tmp/iam_poc.sqlite
```

On Windows with the Access ODBC driver installed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Validate-IAMEnvironment.ps1
python scripts/experiment_01_access_connectivity.py "C:\Users\E385201\OneDrive - Kaiser Permanente\IAMAutomation\iam_automation.accdb"
```

## Key rule

SharePoint or OneDrive sync is not a database server. No application component should write directly to the synchronized `.accdb` except through the coordinator and after lock, backup, working-copy, validation, and audit steps.
