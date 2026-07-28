# Salesforce Export Configuration Guide

## Purpose

IAM Automation generates the Salesforce Data Loader workbook from approved employee requests stored in the local SQLite runtime database. The Salesforce workbook is an **export artifact**. It is not an import source for IAM Automation and the application does not connect to Salesforce or submit the file automatically.

## Official template

The source template is stored in:

`docs/req/salesforce_template/SF PROD TEMPLATE -- KPMA RITM2254022 2025_08_13.xlsx`

The generator preserves the official workbook structure, formulas and formatting. Sample people are removed before output is written. The yellow fields are populated from approved request data.

## Generated output

Files are created under the selected SharePoint-synchronized workspace:

`<SharePoint root>/generated_templates/Salesforce_User_Bulk_YYYYMMDD_HHMMSS.xlsx`

The `generated_templates` folder is created when the first export is generated. Each export receives a unique timestamped filename, so existing artifacts are not overwritten.

## Source and mapping

Only requests with status `APPROVED` and operation `CREATE_EMPLOYEE` or `UPDATE_EMPLOYEE` are included. When multiple approved requests exist for the same employee, the newest approved payload wins.

Current mappings include:

| Salesforce column | IAM payload fields |
| --- | --- |
| `USERNAME` | `username`, `user_name`, or `email` |
| `LASTNAME` | `last_name` or `lastname` |
| `FIRSTNAME` | `first_name` or `firstname` |
| `DIVISION` | `division`, `lob`, or `line_of_business` |
| `DEPARTMENT` | `department` |
| `COUNTRY` / `COUNTRYCODE` | `country` / `country_code` |
| `EMAIL` | `email`, `email_address`, or username |
| `ALIAS` | supplied alias, otherwise first initial plus first four surname characters |
| `EMPLOYEENUMBER` | `employee_id`, `entity_id`, or `worker_id` |
| `NUID__C` | `employee_id`, `entity_id`, or `worker_id` |
| `FEDERATIONIDENTIFIER` | supplied federation identifier, otherwise username |

Salesforce-specific fields such as `PROFILEID`, `USERROLEID`, licensing flags and locale defaults remain governed by the official template until the Salesforce administrator confirms the final values. Do not change those defaults in the application without an approved mapping decision.

## Application procedure

1. Start IAM Automation and complete SharePoint preflight.
2. Sign in with an application account that has `APPLICATION_ADMIN`, `MASTER_ADMIN`, or active temporary `SUPER_OPERATOR` operational access.
3. Create or review the employee request.
4. Obtain reviewer approval. A pending or rejected request is never exported.
5. Open **Administration > Control Center > Salesforce export**.
6. Download the generated workbook and review it with the Salesforce/Data Loader owner.
7. Record the business handoff externally according to the approved Salesforce operating procedure.

The generation event is written to the append-only audit log with the output filename, row count and template name.

## SharePoint and SQLite configuration

On Windows, the SharePoint root must contain the synchronized database snapshot at:

`database/snapshots/iam_runtime.sqlite`

The startup preflight validates and copies that snapshot into the project-local `runtime.sqlite`. The app works on the local copy. Generated Salesforce workbooks are written to the SharePoint `generated_templates` folder, not to the repository.

## Database structure changes

Schema changes are stored in the repository under:

`iam_automation/database/migrations/`

Each migration has an ordered version, a description and an atomic `upgrade()` function. The runtime database records applied migrations in `schema_migrations`. The application never copies a development SQLite file over a data-bearing SharePoint database merely to change its structure.

For a new feature:

1. Add a migration module under `iam_automation/database/migrations/`.
2. Add it to the ordered migration registry in `database/migration_runner.py`.
3. Test it against a fresh database and a database containing representative data.
4. Commit the migration with the application code.
5. Windows downloads the SharePoint snapshot and applies pending migrations locally during startup.
6. `MASTER_ADMIN` reviews and publishes the migrated local snapshot with backup and checksum protection.

The initial implementation registers the existing schema as `v001_initial_schema` and applies `v002_notification_indexes`. Future table, column and relationship changes must be introduced through this mechanism. Business data imports remain a separate validated ingestion workflow.

### macOS development without SharePoint access

macOS cannot publish to the real SharePoint library unless OneDrive is installed and the library is synchronized locally. A SharePoint URL is deliberately rejected by preflight; the application needs a local filesystem path.

Until the Mac has a synchronized library, use the repository fixture as a local SharePoint simulation:

```bash
IAM_SHAREPOINT_ROOT_PATH="$PWD/tests/fixtures/sharepoint_simulated" ./run.sh
```

This validates the complete workflow locally, including SQLite synchronization, generated Salesforce files, backups and manifests. The fixture is not the production SharePoint library. Files generated there are test artifacts and must not be treated as production data.

When testing against the real library, set `IAM_SHAREPOINT_ROOT_PATH` to the local OneDrive-synchronized folder, or select that folder through Browse in the preflight window. If that folder is unavailable on macOS, perform the governed publication from Windows or install/synchronize OneDrive on the Mac first.

## Development workflow between macOS and Windows

During this development phase, the SQLite runtime is the shared operational source and the Access database is not the active application store.

When changes are made on macOS and must be tested on Windows:

1. On macOS without real SharePoint access, use the simulated fixture only for local testing. Do not call that a production publication.
2. On a machine with the real OneDrive library, stop active work that could modify the local runtime.
3. Use **Master Admin > Governance > Publish runtime snapshot**.
4. Confirm the expected checksum and allow the application to create a backup.
5. Let OneDrive synchronize `database/snapshots/iam_runtime.sqlite` and its manifest.
6. On Windows, pull the code branch and run the launcher. Preflight validates the SharePoint snapshot and copies it to the Windows local runtime.
7. Never overwrite the SharePoint snapshot manually and never commit a machine-local `runtime.sqlite` to Git.

If Windows has local administrative changes that must be preserved, publish them first through the same governed action before switching machines. If the checksum changed since download, publication is blocked until the current SharePoint version is refreshed and reviewed.

Git carries code, templates and documentation. SharePoint carries the synchronized runtime snapshot, backups, audit evidence and generated exports. The SQLite file should not be copied over Git or used as a Git-tracked development artifact.
