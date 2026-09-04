# Bug DB-001 — Published Runtime Refresh Alert Appears Late

**Status:** Active investigation  
**Priority:** High  
**Reported:** 2026-09-04  
**Source:** [Meeting notes](../meetings/2026-09-04/notes.md)

## Problem

After another workstation publishes a new runtime SQLite snapshot, the user
does not immediately see the refresh alert. The alert becomes visible after
opening Workspace Overview or manually refreshing the page.

## Impact

Users may continue reviewing stale data and may not understand that a newer
published snapshot exists. The operational impact is currently low, but the
data-freshness risk is real.

## Current evidence

- The file watcher discovers `database/snapshots/iam_runtime.sqlite` and can
  create a local notification (`application/file_watch_service.py`).
- The workspace status endpoint exposes `update_available` in
  `webapp.py`.
- The modal and polling guard are now loaded from the shared authenticated
  `templates/base.html` layout.
- The dashboard no longer owns a second copy of the guard.
- The endpoint remains polled immediately on page load and every five seconds,
  including on Employees, Reports, Administration and Notifications.

## Proposed fix

Move the authenticated workspace freshness guard into the shared layout or a
shared JavaScript module loaded by every authenticated page. Keep the server
endpoint as the source of truth, use `cache: no-store`, prevent duplicate
modals, and preserve the existing explicit refresh action.

The fix must also verify that the watcher and shared publication notification
remain idempotent, especially during OneDrive/SharePoint sync delays.

## Stories and status

| ID | Story | Status | Definition of done |
|---|---|---|---|
| DB-001 | Fix missing refresh notification | Active investigation | Alert appears from any authenticated page after a changed snapshot is detected. |
| DB-002 | Automatic refresh polling | Planned | Shared polling interval/configuration, retry behavior and no duplicate prompts. |
| DB-003 | Publication progress indicator | Planned | Publishing, upload, sync and completed states are visible and tested. |

## Verification matrix

- Publish from workstation A; leave workstation B on Employees.
- Repeat on Reports, Administration and Notifications.
- Verify alert after sync delay without navigation or manual refresh.
- Verify stale data is not replaced automatically; user still confirms refresh.
- Verify pending local requests are preserved and duplicate alerts do not occur.
- Verify watcher failure/recovery and unavailable SharePoint behavior.
