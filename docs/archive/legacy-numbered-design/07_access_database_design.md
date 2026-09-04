# Access Database Design

Initial tables:

- `tbl_Employees`: EmployeeID PK, email unique, manager/vendor/BU/location refs, RecordVersion, audit metadata, IsActive.
- `tbl_Users`: UserID PK, WindowsUsername unique, DisplayName, IsActive.
- `tbl_Roles`: RoleID PK, RoleName unique.
- `tbl_UserRoles`: UserID FK, RoleID FK, unique pair.
- `tbl_ChangeRequests`: RequestID PK, CreatedBy, OperationType, EntityID, ExpectedRecordVersion, PayloadJSON, Status, review/apply metadata.
- `tbl_RequestDecisions`: DecisionID PK, RequestID FK, Decision, DecisionNotes, ReviewedBy, ReviewedAtUTC.
- `tbl_AuditEvents`: AuditID PK, EventType, Actor, RequestID, BatchID, CorrelationID, PreviousValuesJSON, ProposedValuesJSON, Result.
- `tbl_Batches`: BatchID PK, StartedBy, StartedAtUTC, CompletedAtUTC, Status, SummaryJSON.
- `tbl_DatabaseVersions`: DatabaseVersion PK, SchemaVersion, PublishedAtUTC, ChecksumSHA256, BatchID.
- `tbl_Vendors`, `tbl_BusinessUnits`, `tbl_Locations`, `tbl_Managers`: reference data with active flags.
- `tbl_SystemProfiles`, `tbl_TemplateMappings`, `tbl_ExportRuns`: export configuration and run history.
- `tbl_ApplicationVersions`: supported client/schema versions.

Python must enforce JSON schema validation, allowed payload fields, multi-step business rules, idempotency, and some referential checks that Access cannot enforce safely.
