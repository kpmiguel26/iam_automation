# Audit Design

Use append-only audit design, preferably dual logging:

- Access `tbl_AuditEvents`.
- JSONL audit export.

Audit events cover request creation, submission, import, quarantine, review, approval, rejection, conflicts, batch start, change apply, validation, publication, export generation, completion, failure, and recovery.

Do not call JSONL cryptographically immutable unless cryptographic controls are added.
