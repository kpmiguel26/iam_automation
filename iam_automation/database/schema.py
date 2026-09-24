"""
File: iam_automation/database/schema.py
Purpose: Supports runtime database initialization, schema, or migration operations.
Responsibilities: Exposes or coordinates: access_schema_statements.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

ACCESS_SCHEMA_VERSION = "1.0.0"

# Keep the Access schema in one business-oriented module so the initializer,
# documentation, and future migrations share the same source of truth.
ACCESS_TABLES: tuple[str, ...] = (
    "tbl_AppMetadata",
    "tbl_Employees",
    "tbl_Users",
    "tbl_Roles",
    "tbl_UserRoles",
    "tbl_ChangeRequests",
    "tbl_RequestDecisions",
    "tbl_AuditEvents",
    "tbl_Batches",
    "tbl_DatabaseVersions",
    "tbl_Vendors",
    "tbl_BusinessUnits",
    "tbl_Locations",
    "tbl_Managers",
    "tbl_SystemProfiles",
    # DEPRECATED compatibility table; retain for existing Access installations.
    "tbl_TemplateMappings",
    "tbl_ExportRuns",
    "tbl_ApplicationVersions",
)


def access_schema_statements() -> tuple[str, ...]:
    return (
        "CREATE TABLE tbl_AppMetadata (MetadataKey TEXT(100) PRIMARY KEY, MetadataValue MEMO, UpdatedAtUTC DATETIME)",
        "CREATE TABLE tbl_Employees (EmployeeID TEXT(50) PRIMARY KEY, FullName TEXT(255), Email TEXT(255), ManagerID TEXT(50), VendorID TEXT(50), BusinessUnitID TEXT(50), LocationID TEXT(50), EmploymentStatus TEXT(50), StartDate DATETIME, EndDate DATETIME, RecordVersion LONG, IsActive BIT, CreatedAtUTC DATETIME, CreatedBy TEXT(255), ModifiedAtUTC DATETIME, ModifiedBy TEXT(255))",
        "CREATE TABLE tbl_Users (UserID COUNTER PRIMARY KEY, WindowsUsername TEXT(255), DisplayName TEXT(255), IsActive BIT)",
        "CREATE TABLE tbl_Roles (RoleID COUNTER PRIMARY KEY, RoleName TEXT(50))",
        "CREATE TABLE tbl_UserRoles (UserID LONG, RoleID LONG, PRIMARY KEY (UserID, RoleID))",
        "CREATE TABLE tbl_ChangeRequests (RequestID TEXT(36) PRIMARY KEY, CreatedAtUTC DATETIME, CreatedBy TEXT(255), ComputerName TEXT(255), ApplicationVersion TEXT(50), OperationType TEXT(50), EntityType TEXT(50), EntityID TEXT(50), ExpectedRecordVersion LONG, PayloadJSON MEMO, Reason MEMO, Status TEXT(30))",
        "CREATE TABLE tbl_RequestDecisions (DecisionID COUNTER PRIMARY KEY, RequestID TEXT(36), Decision TEXT(30), DecisionNotes MEMO, ReviewedBy TEXT(255), ReviewedAtUTC DATETIME)",
        "CREATE TABLE tbl_AuditEvents (AuditID TEXT(36) PRIMARY KEY, TimestampUTC DATETIME, Actor TEXT(255), ComputerName TEXT(255), EventType TEXT(80), EntityType TEXT(50), EntityID TEXT(50), RequestID TEXT(36), BatchID TEXT(36), CorrelationID TEXT(36), PreviousValuesJSON MEMO, ProposedValuesJSON MEMO, Result TEXT(30), ErrorDetails MEMO)",
        "CREATE TABLE tbl_Batches (BatchID TEXT(36) PRIMARY KEY, StartedBy TEXT(255), StartedAtUTC DATETIME, CompletedAtUTC DATETIME, Status TEXT(30), SummaryJSON MEMO)",
        "CREATE TABLE tbl_DatabaseVersions (DatabaseVersion TEXT(50) PRIMARY KEY, SchemaVersion TEXT(30), PublishedAtUTC DATETIME, ChecksumSHA256 TEXT(64), BatchID TEXT(36))",
        "CREATE TABLE tbl_Vendors (VendorID TEXT(50) PRIMARY KEY, VendorName TEXT(255), IsActive BIT)",
        "CREATE TABLE tbl_BusinessUnits (BusinessUnitID TEXT(50) PRIMARY KEY, BusinessUnitName TEXT(255), IsActive BIT)",
        "CREATE TABLE tbl_Locations (LocationID TEXT(50) PRIMARY KEY, LocationName TEXT(255), IsActive BIT)",
        "CREATE TABLE tbl_Managers (ManagerID TEXT(50) PRIMARY KEY, DisplayName TEXT(255), Email TEXT(255), IsActive BIT)",
        "CREATE TABLE tbl_SystemProfiles (ProfileID COUNTER PRIMARY KEY, ProfileName TEXT(100), ProfileJSON MEMO, IsActive BIT)",
        # DEPRECATED compatibility table; versioned report-template snapshots
        # are the new configuration path. Do not drop this schema here.
        "CREATE TABLE tbl_TemplateMappings (MappingID COUNTER PRIMARY KEY, SystemName TEXT(50), TemplateName TEXT(255), MappingJSON MEMO, IsActive BIT)",
        "CREATE TABLE tbl_ExportRuns (ExportRunID COUNTER PRIMARY KEY, SystemName TEXT(50), TemplateName TEXT(255), BatchID TEXT(36), StartedAtUTC DATETIME, CompletedAtUTC DATETIME, Status TEXT(30), OutputPath MEMO, ErrorDetails MEMO)",
        "CREATE TABLE tbl_ApplicationVersions (ApplicationVersion TEXT(50) PRIMARY KEY, MinimumSchemaVersion TEXT(30), ReleasedAtUTC DATETIME, IsSupported BIT)",
        "CREATE UNIQUE INDEX UX_tbl_Users_WindowsUsername ON tbl_Users (WindowsUsername)",
        "CREATE UNIQUE INDEX UX_tbl_Roles_RoleName ON tbl_Roles (RoleName)",
        "CREATE UNIQUE INDEX UX_tbl_Employees_Email ON tbl_Employees (Email)",
        "INSERT INTO tbl_AppMetadata (MetadataKey, MetadataValue, UpdatedAtUTC) VALUES ('schema_version', '1.0.0', NOW())",
    )
#endfile
