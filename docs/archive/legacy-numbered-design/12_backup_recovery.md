# Backup and Recovery

Before applying changes:

- Record current snapshot version and checksum.
- Create timestamped local backup.
- Copy Access snapshot to local workspace outside OneDrive.

Before publication:

- Close Access connection.
- Reopen and verify database.
- Compute checksum.
- Re-read published version/checksum.
- Abort if the source changed.

Requests are archived only after successful publication.
