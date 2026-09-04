# Risk Register

| Risk | Severity | Status | Mitigation |
| --- | --- | --- | --- |
| OneDrive conflict during Access write | High | Open | Local working copy, app lock, backup, publish step, manual sync tests |
| Multiple writers overwrite each other | High | Open | Application lock plus optimistic concurrency |
| Stale local copy is published | High | Open | Checksums and publication manifest before write |
| Access file corruption | High | Open | Timestamped backups and verification after writes |
| Access ODBC driver missing or incompatible | Medium | Open | Environment validation script |
| Unapproved user runs write operation | High | In progress | Windows username plus approved-user CSV |
| Audit lost after failed database write | Medium | In progress | Append-only JSONL audit outside database |
