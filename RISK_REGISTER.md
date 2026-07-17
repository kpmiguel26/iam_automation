# Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Multiple apps write directly to the same `.accdb` | Lost updates, corruption, conflict copies | Prohibit direct client writes; use immutable request files and single-writer workflow |
| Multiple administrators process batches simultaneously | Competing master versions and duplicate processing | Restrict writer permissions, handoff policy, advisory marker, activity log, version check before publish |
| OneDrive synchronization delay | Stale snapshots and delayed requests | Versioned filenames, sync confirmation, no overwrite without version verification |
| Request file processed twice | Duplicate updates or exports | UUID `request_id`, unique index, idempotent registry |
| Malformed or malicious JSON | Invalid data or application failure | Strict schema validation, max file size, allowed operations, quarantine |
| Published database changes during processing | Admin overwrites newer version | Record initial version/checksum and abort if changed |
| Access database corruption | Loss of master data | Local processing, backups, versioned snapshots, integrity verification |
| Administrator workstation failure | Interrupted batch | Batch journal, idempotent reprocessing, archive only after publish |
| Weak identity or spoofing | Unauthorized request/approval | Windows identity capture, approved-user roles, audit, future Entra ID |
| Sensitive employee data in request files | Data exposure | Least-privilege folders, data minimization, retention policy |
| Old application versions | Invalid schemas | Version in each request, minimum supported version, quarantine incompatible files |
| Access and JSON state diverge | Request says applied but snapshot not published | State transitions after verified publication, reconciliation report |
