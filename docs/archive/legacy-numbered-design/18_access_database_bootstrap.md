# Access Database Bootstrap

## Target database

The first master snapshot is a Microsoft Access `.accdb` file stored in the local OneDrive-synchronized SharePoint folder. The file is excluded from source control because it contains operational data.

## Windows initialization

On Windows with the Microsoft Access Database Engine and ODBC driver installed:

```bat
python scripts\create_access_database.py "C:\path\to\OneDrive - Organization\IAMAutomation\iam_automation.accdb"
```

The initializer creates the file through ADOX when it does not exist, then applies schema version `1.0.0`. Re-running the command is safe: existing tables, indexes, and schema metadata are skipped.

## macOS development

The macOS environment does not provide the Microsoft Access ODBC/ADOX stack. It must not generate an empty file with an `.accdb` extension and call it a database. Use the following command to inspect the exact DDL:

```bash
./.venv/bin/python scripts/create_access_database.py placeholder.accdb --show-schema
```

The actual `.accdb` must be created and initialized on the target Windows environment, after which the startup preflight can discover it through the synchronized SharePoint folder.

## Runtime SQLite snapshot

The published runtime database is expected at `database/snapshots/iam_runtime.sqlite`. The application validates it with SQLite integrity checks and a companion `iam_runtime.manifest.json` checksum. It is copied to `runtime.sqlite` in the project root for local development; that file is ignored by Git.

Create the first runtime database on macOS and publish it to a selected SharePoint-synced path:

```bash
./.venv/bin/python scripts/create_runtime_database.py --publish-root "/path/to/IAMAutomation"
```

Refresh the local copy later:

```bash
./.venv/bin/python scripts/sync_runtime_database.py "/path/to/IAMAutomation"
```

Publish an administrative local change with a backup and concurrency check:

```bash
./.venv/bin/python scripts/sync_runtime_database.py "/path/to/IAMAutomation" --publish --actor "DOMAIN\\admin" --expected-checksum "<checksum-from-manifest>"
```

## Initial schema areas

The bootstrap includes employees, users, roles, user-role assignments, change requests, request decisions, audit events, batches, database versions, reference data, template mappings, export runs, system profiles, and application versions.
