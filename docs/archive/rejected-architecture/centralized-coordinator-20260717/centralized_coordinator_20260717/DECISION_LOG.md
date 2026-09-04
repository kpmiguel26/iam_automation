# Decision Log

## 2026-07-17: Start with POC, not full IAM app

Status: Accepted

The first milestone is a feasibility assessment for Access, SharePoint/OneDrive synchronization, locks, concurrency, user validation, backups, and recovery.

## 2026-07-17: Reject SharePoint web URLs as runtime database paths

Status: Accepted

The application must work with the local OneDrive-synced path, mirroring the established `scrapping` path validation pattern.

## 2026-07-17: Keep workspace outside OneDrive

Status: Accepted

Working database copies must be local first, then published only after validation.
