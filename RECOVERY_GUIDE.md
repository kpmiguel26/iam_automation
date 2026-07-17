# Recovery Guide

## Principles

- Do not archive request files until publication succeeds.
- Use `request_id` as the idempotency key.
- Use `batch_id` and `correlation_id` for recovery.
- Preserve failed and quarantined evidence.

## Common Recovery Cases

- Process stops before archive: rerun import; duplicates are rejected safely.
- Process stops after local Access update but before publication: discard local copy or resume using batch journal.
- Process stops after publication but before status update: reconcile manifest, Access tables, and request folders.
- Published version changed during processing: abort, compare manifests, and restart from latest snapshot.
- Access corruption: restore prior versioned snapshot or SharePoint version history.
