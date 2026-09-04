# Proof of Concept Plan

Build only the minimum POC:

1. Windows user identification.
2. Role validation.
3. Request JSON creation and schema validation.
4. Unique request submission.
5. Duplicate request rejection.
6. Access connectivity through `pyodbc`.
7. Import into `tbl_ChangeRequests`.
8. Admin approval/rejection.
9. Apply approved request.
10. Record-version conflict detection.
11. Audit JSONL generation.
12. Backup, checksum, snapshot versioning.
13. Publication precondition validation.
14. Idempotent batch reprocessing.
15. Example Excel output.
16. Reconciliation report.
