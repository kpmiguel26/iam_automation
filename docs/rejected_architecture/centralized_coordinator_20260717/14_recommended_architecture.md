# Recommended Architecture

Provisional recommendation: local working copy plus controlled publication, guarded by an application lock, user validation, backups, audit events, checksums, and optimistic concurrency.

If multiple people need frequent writes, the safer recommendation is a single-writer workstation or service that serializes all write operations.

Direct multi-user writes to the OneDrive-synced `.accdb` should be considered unsafe unless the POC produces unusually strong evidence.
