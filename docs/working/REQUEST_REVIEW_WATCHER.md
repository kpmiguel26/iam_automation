# Automatic Request Review Workflow

## Purpose

Files discovered in the shared workspace are reviewable business inputs. Discovery does not silently create or update canonical employees. The watcher stages the source rows, creates one shared pending request, and notifies the eligible reviewers and administrators.

## Monitored Sources

- `rosterlocks/` creates an `IMPORT_ROSTER_LOCK` request.
- `rsrsuplierworkerdetails/` creates an `IMPORT_RSR_SUPPLIER_DETAILS` request.
- Other configured files continue to produce a file-detected notification until their ingestion adapter is enabled.

## Request Contents

Each automatic import request contains the batch ID, source filename, checksum, source system, row counts, staged record IDs, and portable record previews. The previews allow a reviewer to see the proposed employee data, identifier, vendor or statement of work, and match status before a decision.

The request is idempotent by batch or source checksum. Re-scanning the same file does not create another pending request.

## Visibility and Decisions

1. A new request is persisted in the shared request store.
2. Active `REVIEWER`, `APPLICATION_ADMIN`, `MASTER_ADMIN`, `SUPER_OPERATOR`, and legacy `ADMINISTRATOR` accounts receive an in-app review notification.
3. Reviewers can open the full payload and business reason.
4. The employee profile provides a source comparison page. It shows only staged rows that match the employee and only fields whose incoming value differs from the canonical value. New or unmatched source rows are shown separately as new employee candidates.
5. The comparison page is read-only. It does not change the canonical worker and does not force a one-row-at-a-time workflow. A later request can use the reviewed delta as its payload; the existing import request remains the controlled approval boundary.
6. A requester-only account can see the queue but cannot record a decision. An administrator may approve their own request when operationally required. The action requires a review note and is audited as `ADMIN_SELF_APPROVAL`.
7. Approval applies eligible staged records locally. Publication of the runtime snapshot remains a separate controlled action and generates a publication notification when required.

Rejections require a decision note. Both decisions and publication requests remain in the audit trail.

## Failure Handling

The watcher confirms file observations before opening the ingestion transaction, uses a process write lock, retries transient SQLite contention, and records ingestion failures as notifications. A single malformed file or temporary database lock must not terminate the watcher thread.
