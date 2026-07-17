# Operating Model

## Single-Writer Policy

Only one Administrator/Writer processes a batch at a time. Because there is no central lock authority, a lock file may be used only as an advisory marker, not as a guarantee of distributed mutual exclusion.

## Writer Batch Steps

1. Validate administrator identity and role.
2. Validate application version.
3. Record batch ID and correlation ID.
4. Check current published snapshot version and checksum.
5. Copy the published Access snapshot to a local workspace outside OneDrive.
6. Import pending request files by `request_id`.
7. Quarantine malformed or suspicious files.
8. Reject duplicates.
9. Review and approve or reject requests.
10. Apply approved non-conflicting changes.
11. Validate referential integrity.
12. Generate audit events and Excel outputs.
13. Create a versioned Access snapshot and manifest.
14. Re-check published version before publication.
15. Publish only if the source version did not change.
16. Archive processed request files.
17. Write batch summary.

## Handoff

If multiple people have writer permissions, they must use a documented handoff process and batch activity log.
