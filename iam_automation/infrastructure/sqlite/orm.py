"""
File: iam_automation/infrastructure/sqlite/orm.py
Purpose: Provides SQLite persistence infrastructure for orm.
Responsibilities: Exposes or coordinates: Base, AppUserModel, UserRoleModel, ApprovedUserModel, RoleModel, ….
Dependencies: sqlalchemy
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class AppUserModel(Base):
    __tablename__ = "app_users"

    username: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    password_hash: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    roles: Mapped[list["UserRoleModel"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    username: Mapped[str] = mapped_column(ForeignKey("app_users.username"), primary_key=True)
    role_name: Mapped[str] = mapped_column(String, primary_key=True)
    user: Mapped[AppUserModel] = relationship(back_populates="roles")


class ApprovedUserModel(Base):
    __tablename__ = "approved_users"

    username: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoleModel(Base):
    __tablename__ = "roles"

    role_name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DelegationModel(Base):
    __tablename__ = "admin_delegations"

    delegation_id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_username: Mapped[str] = mapped_column(String)
    delegate_username: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    starts_at_utc: Mapped[str] = mapped_column(String)
    expires_at_utc: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    revoked_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


class ChangeRequestModel(Base):
    __tablename__ = "change_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at_utc: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    computer_name: Mapped[str] = mapped_column(String)
    application_version: Mapped[str] = mapped_column(String)
    operation_type: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    expected_record_version: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class ApprovalAssignmentModel(Base):
    __tablename__ = "approval_assignments"

    assignment_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String)
    assigned_to: Mapped[str] = mapped_column(String)
    assigned_by: Mapped[str] = mapped_column(String)
    assigned_at_utc: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(Text)


class PublicationQueueModel(Base):
    __tablename__ = "publication_queue"

    publication_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="PENDING_PUBLICATION")
    queued_by: Mapped[str] = mapped_column(String)
    queued_at_utc: Mapped[str] = mapped_column(String)
    processed_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SessionRevocationModel(Base):
    __tablename__ = "session_revocations"

    revocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    revoked_by: Mapped[str] = mapped_column(String)
    revoked_at_utc: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)


class ImportBatchModel(Base):
    __tablename__ = "import_batches"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="COMPLETED_WITH_WARNINGS")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    quarantine_rows: Mapped[int] = mapped_column(Integer, default=0)
    filtered_rows: Mapped[int] = mapped_column(Integer, default=0)
    termination_window_start: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    source_modified_at_utc: Mapped[str] = mapped_column(String, default="")
    completed_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuarantineRecordModel(Base):
    __tablename__ = "quarantine_records"

    quarantine_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String)
    row_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="OPEN")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


class IngestionRecordModel(Base):
    __tablename__ = "ingestion_records"
    __table_args__ = (UniqueConstraint("source_file", "source_checksum", "row_number", name="uq_ingestion_source_row"),)

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String)
    source_system: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String)
    source_checksum: Mapped[str] = mapped_column(String)
    row_number: Mapped[int] = mapped_column(Integer)
    source_record_key: Mapped[str] = mapped_column(String)
    normalized_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="STAGED")
    match_status: Mapped[str] = mapped_column(String, default="NOT_EVALUATED")
    matched_worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_reason: Mapped[str] = mapped_column(Text, default="")
    observation_state: Mapped[str] = mapped_column(String, default="PENDING")
    superseded_by_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerModel(Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    display_name: Mapped[str] = mapped_column(String, default="")
    canonical_email: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="PENDING")
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by_worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerIdentifierModel(Base):
    __tablename__ = "worker_identifiers"
    __table_args__ = (UniqueConstraint("source_system", "identifier_type", "normalized_value", name="uq_worker_identifier"),)

    identifier_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    source_system: Mapped[str] = mapped_column(String)
    identifier_type: Mapped[str] = mapped_column(String)
    identifier_value: Mapped[str] = mapped_column(String)
    normalized_value: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[str] = mapped_column(String, default="HIGH")
    valid_from_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_to_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerSourceProfileModel(Base):
    """Current source-specific identity/profile projection for one worker."""

    __tablename__ = "worker_source_profiles"
    __table_args__ = (UniqueConstraint("source_system", "source_record_key", name="uq_worker_source_profile_key"),)

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    source_system: Mapped[str] = mapped_column(String)
    source_record_key: Mapped[str] = mapped_column(String)
    current_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String, default="CURRENT")
    first_seen_at_utc: Mapped[str] = mapped_column(String, default="")
    last_seen_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerEngagementModel(Base):
    __tablename__ = "worker_engagements"

    engagement_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    vendor_name: Mapped[str] = mapped_column(String, default="")
    program: Mapped[str] = mapped_column(String, default="")
    project: Mapped[str] = mapped_column(String, default="")
    lob: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    country: Mapped[str] = mapped_column(String, default="")
    site_location: Mapped[str] = mapped_column(String, default="")
    onboarding_date: Mapped[str] = mapped_column(String, default="")
    production_start_date: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="PENDING")
    npn: Mapped[str] = mapped_column(String, default="")
    license_state: Mapped[str] = mapped_column(String, default="")
    license_number: Mapped[str] = mapped_column(String, default="")
    taxonomy_code: Mapped[str] = mapped_column(String, default="")
    key_billable_function: Mapped[str] = mapped_column(String, default="")
    statement_of_work: Mapped[str] = mapped_column(String, default="")
    work_order_id: Mapped[str] = mapped_column(String, default="")
    primary_contact_name: Mapped[str] = mapped_column(String, default="")
    source_system: Mapped[str] = mapped_column(String, default="")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerSourceLineageModel(Base):
    __tablename__ = "worker_source_lineage"

    lineage_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    engagement_id: Mapped[str | None] = mapped_column(String, nullable=True)
    batch_id: Mapped[str] = mapped_column(String)
    source_system: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String)
    source_checksum: Mapped[str] = mapped_column(String)
    row_number: Mapped[int] = mapped_column(Integer)
    field_name: Mapped[str] = mapped_column(String)
    raw_value: Mapped[str] = mapped_column(Text, default="")
    normalized_value: Mapped[str] = mapped_column(Text, default="")
    observed_at_utc: Mapped[str] = mapped_column(String, default="")


class FieldCatalogModel(Base):
    """Governed fields allowed in the compact current-state projection."""

    __tablename__ = "field_catalog"

    field_key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, default="")
    data_type: Mapped[str] = mapped_column(String, default="TEXT")
    sensitivity: Mapped[str] = mapped_column(String, default="INTERNAL")
    reportable: Mapped[bool] = mapped_column(Boolean, default=True)
    rule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class EmployeeFieldValueModel(Base):
    """One current value per employee, source, and governed field."""

    __tablename__ = "employee_field_values"
    __table_args__ = (UniqueConstraint("worker_id", "source_system", "field_key", name="uq_employee_field_current"),)

    value_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    source_system: Mapped[str] = mapped_column(String)
    field_key: Mapped[str] = mapped_column(ForeignKey("field_catalog.field_key"))
    value_text: Mapped[str] = mapped_column(Text, default="")
    source_record_key: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[str] = mapped_column(String, default="")
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class DimSourceModel(Base):
    __tablename__ = "dim_source"
    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_system: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DimFieldModel(Base):
    __tablename__ = "dim_field"
    field_id: Mapped[str] = mapped_column(String, primary_key=True)
    field_key: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String, default="")
    data_type: Mapped[str] = mapped_column(String, default="TEXT")
    sensitivity: Mapped[str] = mapped_column(String, default="INTERNAL")
    reportable: Mapped[bool] = mapped_column(Boolean, default=True)
    rule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    semantic_type: Mapped[str] = mapped_column(String, default="TEXT")
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_operators_json: Mapped[str] = mapped_column(Text, default="[]")
    normalization_name: Mapped[str] = mapped_column(String, default="identity")
    metadata_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String, default="system")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class DimDateModel(Base):
    __tablename__ = "dim_date"
    date_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    calendar_date: Mapped[str] = mapped_column(String, unique=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    day: Mapped[int] = mapped_column(Integer)
    day_of_week: Mapped[int] = mapped_column(Integer)
    is_weekend: Mapped[bool] = mapped_column(Boolean, default=False)


class RuleCalendarModel(Base):
    __tablename__ = "rule_calendars"

    calendar_id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_key: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class RuleCalendarVersionModel(Base):
    __tablename__ = "rule_calendar_versions"
    __table_args__ = (UniqueConstraint("calendar_id", "version", name="uq_rule_calendar_version"),)

    calendar_version_id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_id: Mapped[str] = mapped_column(ForeignKey("rule_calendars.calendar_id"))
    version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    operating_weekdays_json: Mapped[str] = mapped_column(Text, default="[0,1,2,3,4]")
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class RuleCalendarHolidayModel(Base):
    __tablename__ = "rule_calendar_holidays"
    __table_args__ = (UniqueConstraint("calendar_version_id", "holiday_date", "label", name="uq_rule_calendar_holiday"),)

    holiday_id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_version_id: Mapped[str] = mapped_column(ForeignKey("rule_calendar_versions.calendar_version_id"))
    holiday_date: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, default="")
    recurring_annually: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String, default="MANUAL")
    source_country: Mapped[str] = mapped_column(String, default="")
    source_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    holiday_type: Mapped[str] = mapped_column(String, default="")
    observed_date: Mapped[str | None] = mapped_column(String, nullable=True)


class RuleContextModel(Base):
    __tablename__ = "rule_contexts"

    context_id: Mapped[str] = mapped_column(String, primary_key=True)
    context_key: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class RuleContextVersionModel(Base):
    __tablename__ = "rule_context_versions"
    __table_args__ = (UniqueConstraint("context_id", "version", name="uq_rule_context_version"),)

    context_version_id: Mapped[str] = mapped_column(String, primary_key=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("rule_contexts.context_id"))
    version: Mapped[int] = mapped_column(Integer)
    default_calendar_id: Mapped[str] = mapped_column(ForeignKey("rule_calendars.calendar_id"))
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    missing_data_behavior: Mapped[str] = mapped_column(String, default="FINDING")
    date_boundary: Mapped[str] = mapped_column(String, default="EXCLUSIVE_START_INCLUSIVE_END")
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class DimVendorModel(Base):
    __tablename__ = "dim_vendor"
    vendor_id: Mapped[str] = mapped_column(String, primary_key=True)
    vendor_name: Mapped[str] = mapped_column(String, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DimEmployeeModel(Base):
    """Canonical employee dimension. Status is deliberately excluded here."""

    __tablename__ = "dim_employee"

    employee_key: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    display_name: Mapped[str] = mapped_column(String, default="")
    canonical_email: Mapped[str] = mapped_column(String, default="")
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by_employee_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class BridgeEmployeeIdentifierModel(Base):
    """Maps source identifiers to the canonical employee dimension."""

    __tablename__ = "bridge_employee_identifier"
    __table_args__ = (
        UniqueConstraint("source_system", "identifier_type", "normalized_value", name="uq_employee_identifier"),
    )

    employee_identifier_key: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str] = mapped_column(ForeignKey("dim_employee.employee_key"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_system: Mapped[str] = mapped_column(String)
    identifier_type: Mapped[str] = mapped_column(String)
    identifier_value: Mapped[str] = mapped_column(String)
    normalized_value: Mapped[str] = mapped_column(String)
    source_record_id: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[str] = mapped_column(String, default="HIGH")
    valid_from_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_to_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class SourceFieldMappingModel(Base):
    """Administrator-managed mapping from a source column to a governed field."""

    __tablename__ = "source_field_mapping"
    __table_args__ = (
        UniqueConstraint("source_id", "source_field_key", "mapping_version", name="uq_source_field_mapping"),
        CheckConstraint("target_kind IN ('DIMENSION', 'FACT', 'IDENTIFIER', 'STATUS', 'IGNORE')", name="ck_mapping_target_kind"),
    )

    mapping_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_field_key: Mapped[str] = mapped_column(String)
    field_id: Mapped[str | None] = mapped_column(ForeignKey("dim_field.field_id"), nullable=True)
    target_kind: Mapped[str] = mapped_column(String, default="FACT")
    transform_name: Mapped[str] = mapped_column(String, default="identity")
    mapping_version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from_utc: Mapped[str] = mapped_column(String, default="")
    effective_to_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class FieldOwnershipModel(Base):
    """Declares which source is allowed to write a governed field."""

    __tablename__ = "field_ownership"
    __table_args__ = (
        UniqueConstraint("field_id", "effective_from_utc", name="uq_field_ownership_period"),
        CheckConstraint("write_policy IN ('APPEND_ONLY', 'STATUS_OWNER', 'READ_ONLY')", name="ck_field_write_policy"),
    )

    ownership_id: Mapped[str] = mapped_column(String, primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("dim_field.field_id"))
    owner_source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    write_policy: Mapped[str] = mapped_column(String, default="APPEND_ONLY")
    effective_from_utc: Mapped[str] = mapped_column(String, default="")
    effective_to_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class EmployeeIdentityRuleModel(Base):
    """Ordered, administrator-managed identity matching rules."""

    __tablename__ = "employee_identity_rule"
    __table_args__ = (
        UniqueConstraint("source_id", "identifier_type", "priority", name="uq_employee_identity_rule"),
        CheckConstraint("match_mode IN ('EXACT', 'NORMALIZED_EXACT')", name="ck_identity_match_mode"),
    )

    rule_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    field_id: Mapped[str] = mapped_column(ForeignKey("dim_field.field_id"))
    identifier_type: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    match_mode: Mapped[str] = mapped_column(String, default="NORMALIZED_EXACT")
    allow_employee_creation: Mapped[bool] = mapped_column(Boolean, default=True)
    unique_scope: Mapped[str] = mapped_column(String, default="SOURCE")
    effective_from_utc: Mapped[str] = mapped_column(String, default="")
    effective_to_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class FactSourceSnapshotModel(Base):
    __tablename__ = "fact_source_snapshot"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", "source_record_key", name="uq_star_snapshot"),)
    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_key: Mapped[str] = mapped_column(String)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="CURRENT")
    retention_rank: Mapped[int] = mapped_column(Integer, default=1)


class FactWorkerFieldModel(Base):
    __tablename__ = "fact_worker_field"
    __table_args__ = (UniqueConstraint("snapshot_id", "field_id", name="uq_star_field"),)
    field_value_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("fact_source_snapshot.snapshot_id"))
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"), nullable=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("dim_field.field_id"))
    value_text: Mapped[str] = mapped_column(Text, default="")


class FactTerminationModel(Base):
    __tablename__ = "fact_termination"
    termination_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("fact_source_snapshot.snapshot_id"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"), nullable=True)
    date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    termination_date: Mapped[str] = mapped_column(String, default="")
    termination_type: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="ACTIVE")


class FactAssignmentModel(Base):
    __tablename__ = "fact_assignment"
    assignment_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("fact_source_snapshot.snapshot_id"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"), nullable=True)
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("dim_vendor.vendor_id"), nullable=True)
    work_order_id: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="ACTIVE")


class FactWorkerFieldHistoryModel(Base):
    __tablename__ = "fact_worker_field_history"
    __table_args__ = (UniqueConstraint("worker_id", "source_system", "field_key", "version_number", name="uq_star_field_history"),)
    history_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    source_system: Mapped[str] = mapped_column(String, default="CANONICAL")
    field_key: Mapped[str] = mapped_column(String)
    value_text: Mapped[str] = mapped_column(Text, default="")
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    source_file: Mapped[str] = mapped_column(String, default="")


class FactQuarantineModel(Base):
    """Master fact for rule violations observed during source ingestion."""

    __tablename__ = "fact_quarantine"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_fact_quarantine_finding"),)

    quarantine_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("dim_source.source_id"), nullable=True)
    field_id: Mapped[str | None] = mapped_column(ForeignKey("dim_field.field_id"), nullable=True)
    source_system: Mapped[str] = mapped_column(String, default="")
    source_record_key: Mapped[str] = mapped_column(String, default="")
    rule_id: Mapped[str] = mapped_column(String)
    rule_version_id: Mapped[str] = mapped_column(String)
    field_key: Mapped[str] = mapped_column(String, default="")
    operator: Mapped[str] = mapped_column(String, default="")
    expected_value: Mapped[str] = mapped_column(Text, default="")
    observed_value: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String, default="WARNING")
    status: Mapped[str] = mapped_column(String, default="OPEN")
    rule_name: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


class FactAccessNowEmployeeModel(Base):
    """Append-only typed facts from the AccessNow employee report."""

    __tablename__ = "fact_accessnow_employee"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", "source_record_key", name="uq_accessnow_fact"),)

    accessnow_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_key: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String, default="")
    source_checksum: Mapped[str] = mapped_column(String, default="")
    row_number: Mapped[int] = mapped_column(Integer, default=0)
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    accessnow_employee_id: Mapped[str] = mapped_column(String, default="")
    accessnow_nuid: Mapped[str] = mapped_column(String, default="")
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    vendor_name: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    manager_nuid: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    sponsor_nuid: Mapped[str] = mapped_column(String, default="")
    sponsor_name: Mapped[str] = mapped_column(String, default="")
    accessnow_status: Mapped[str] = mapped_column(String, default="")
    termination_date: Mapped[str] = mapped_column(String, default="")
    onboarding_date: Mapped[str] = mapped_column(String, default="")
    production_start_date: Mapped[str] = mapped_column(String, default="")


class FactMasterRosterEmployeeModel(Base):
    """Append-only typed facts from the master roster report."""

    __tablename__ = "fact_master_roster_employee"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", "source_record_key", name="uq_master_roster_fact"),)

    master_roster_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_key: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String, default="")
    source_checksum: Mapped[str] = mapped_column(String, default="")
    row_number: Mapped[int] = mapped_column(Integer, default=0)
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    employee_number: Mapped[str] = mapped_column(String, default="")
    nuid_login_id: Mapped[str] = mapped_column(String, default="")
    npn_login_id: Mapped[str] = mapped_column(String, default="")
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    parent_client: Mapped[str] = mapped_column(String, default="")
    client: Mapped[str] = mapped_column(String, default="")
    program: Mapped[str] = mapped_column(String, default="")
    project: Mapped[str] = mapped_column(String, default="")
    site_hr_location: Mapped[str] = mapped_column(String, default="")
    supervisor_employee_number: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    job_code: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    hire_date: Mapped[str] = mapped_column(String, default="")
    project_start_date: Mapped[str] = mapped_column(String, default="")
    production_start_date: Mapped[str] = mapped_column(String, default="")
    actual_termination_date: Mapped[str] = mapped_column(String, default="")
    term_reason: Mapped[str] = mapped_column(String, default="")
    assignment_status: Mapped[str] = mapped_column(String, default="")
    user_principal_name: Mapped[str] = mapped_column(String, default="")


class FactRosterLockAssignmentModel(Base):
    """Append-only typed facts from the roster lock assignment report."""

    __tablename__ = "fact_roster_lock_assignment"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", "source_record_key", name="uq_roster_lock_fact"),)

    roster_lock_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_key: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String, default="")
    source_checksum: Mapped[str] = mapped_column(String, default="")
    row_number: Mapped[int] = mapped_column(Integer, default=0)
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    vendor_name: Mapped[str] = mapped_column(String, default="")
    vendor_employee_id: Mapped[str] = mapped_column(String, default="")
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    onboarding_date: Mapped[str] = mapped_column(String, default="")
    production_start_date: Mapped[str] = mapped_column(String, default="")
    assignment_status: Mapped[str] = mapped_column(String, default="")
    work_order_id: Mapped[str] = mapped_column(String, default="")


class FactRsrAssignmentModel(Base):
    """Append-only typed facts from the RSR supplier report."""

    __tablename__ = "fact_rsr_assignment"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", "source_record_key", name="uq_rsr_fact"),)

    rsr_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_key: Mapped[str] = mapped_column(String)
    source_file: Mapped[str] = mapped_column(String, default="")
    source_checksum: Mapped[str] = mapped_column(String, default="")
    row_number: Mapped[int] = mapped_column(Integer, default=0)
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    supplier_reference: Mapped[str] = mapped_column(String, default="")
    worker_id: Mapped[str] = mapped_column(String, default="")
    buyer_reference: Mapped[str] = mapped_column(String, default="")
    work_order_id: Mapped[str] = mapped_column(String, default="")
    worker: Mapped[str] = mapped_column(String, default="")
    first_name: Mapped[str] = mapped_column(String, default="")
    last_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    vendor_name: Mapped[str] = mapped_column(String, default="")
    worker_status: Mapped[str] = mapped_column(String, default="")
    worker_start_date: Mapped[str] = mapped_column(String, default="")
    worker_end_date: Mapped[str] = mapped_column(String, default="")
    job_title: Mapped[str] = mapped_column(String, default="")
    supervisor_name: Mapped[str] = mapped_column(String, default="")
    statement_of_work: Mapped[str] = mapped_column(String, default="")
    supplier_name: Mapped[str] = mapped_column(String, default="")


class FactEmployeeStatusEventModel(Base):
    """AccessNow-owned employee status events."""

    __tablename__ = "fact_employee_status_event"
    __table_args__ = (
        UniqueConstraint("employee_key", "source_record_id", "status_code", name="uq_employee_status_event"),
        CheckConstraint("owner_source_system = 'ACCESSNOW'", name="ck_status_owner_accessnow"),
    )

    status_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str] = mapped_column(ForeignKey("dim_employee.employee_key"))
    accessnow_fact_id: Mapped[str] = mapped_column(ForeignKey("fact_accessnow_employee.accessnow_fact_id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_id: Mapped[str] = mapped_column(String)
    status_code: Mapped[str] = mapped_column(String)
    effective_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    effective_date: Mapped[str] = mapped_column(String, default="")
    owner_source_system: Mapped[str] = mapped_column(String, default="ACCESSNOW")
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class FactSourceFieldValueModel(Base):
    """Governed overflow for source fields not yet promoted to typed columns."""

    __tablename__ = "fact_source_field_value"
    __table_args__ = (
        UniqueConstraint("source_system", "source_record_id", "field_id", name="uq_source_field_value"),
    )

    source_value_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str | None] = mapped_column(ForeignKey("dim_employee.employee_key"), nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_system: Mapped[str] = mapped_column(String)
    source_record_id: Mapped[str] = mapped_column(String)
    source_record_key: Mapped[str] = mapped_column(String, default="")
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"))
    field_id: Mapped[str] = mapped_column(ForeignKey("dim_field.field_id"))
    value_text: Mapped[str] = mapped_column(Text, default="")
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")


class FactEmployeeFieldHistoryModel(Base):
    """Append-only employee field history; retention service keeps three versions."""

    __tablename__ = "fact_employee_field_history"
    __table_args__ = (
        UniqueConstraint("employee_key", "field_id", "version_number", name="uq_employee_field_history"),
    )

    history_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_key: Mapped[str] = mapped_column(ForeignKey("dim_employee.employee_key"))
    field_id: Mapped[str] = mapped_column(ForeignKey("dim_field.field_id"))
    owner_source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    source_record_id: Mapped[str] = mapped_column(String, default="")
    value_text: Mapped[str] = mapped_column(Text, default="")
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    observed_date_key: Mapped[int | None] = mapped_column(ForeignKey("dim_date.date_key"), nullable=True)
    observed_at_utc: Mapped[str] = mapped_column(String, default="")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerDiscrepancyModel(Base):
    __tablename__ = "worker_discrepancies"

    discrepancy_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_system: Mapped[str] = mapped_column(String)
    source_record_key: Mapped[str] = mapped_column(String)
    field_name: Mapped[str] = mapped_column(String)
    current_value: Mapped[str] = mapped_column(Text, default="")
    incoming_value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="OPEN")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


class WorkerProfileVersionModel(Base):
    """Immutable canonical worker snapshot kept for audit and rollback review."""

    __tablename__ = "worker_profile_versions"
    __table_args__ = (UniqueConstraint("worker_id", "version_number", name="uq_worker_profile_version"),)

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    version_number: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String, default="SOURCE_IMPORT")
    snapshot_json: Mapped[str] = mapped_column(Text)
    changed_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    source_system: Mapped[str] = mapped_column(String, default="")
    source_file: Mapped[str] = mapped_column(String, default="")
    source_checksum: Mapped[str] = mapped_column(String, default="")
    source_record_key: Mapped[str] = mapped_column(String, default="")
    actor: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class WorkerMergeEventModel(Base):
    """Records duplicate resolution without deleting either worker record."""

    __tablename__ = "worker_merge_events"

    merge_id: Mapped[str] = mapped_column(String, primary_key=True)
    survivor_worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    duplicate_worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class SystemProfileModel(Base):
    __tablename__ = "system_profiles"

    profile_name: Mapped[str] = mapped_column(String, primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FileObservationModel(Base):
    __tablename__ = "file_observations"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    file_kind: Mapped[str] = mapped_column(String)
    signature: Mapped[str] = mapped_column(String)
    first_seen_at_utc: Mapped[str] = mapped_column(String, default="")
    last_seen_at_utc: Mapped[str] = mapped_column(String, default="")


class TemporaryElevationModel(Base):
    __tablename__ = "temporary_elevations"

    elevation_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    starts_at_utc: Mapped[str] = mapped_column(String)
    expires_at_utc: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    granted_by: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    revoked_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")


class BusinessRuleModel(Base):
    """User-managed rule definition; evaluation is always post-import."""

    __tablename__ = "business_rules"

    rule_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    rule_type: Mapped[str] = mapped_column(String, default="RECORD_CONDITION")
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")


class BusinessRuleVersionModel(Base):
    __tablename__ = "business_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_business_rule_version"),)

    rule_version_id: Mapped[str] = mapped_column(String, primary_key=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("business_rules.rule_id"))
    version: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String, default="AFTER", server_default="AFTER")
    context_version_id: Mapped[str | None] = mapped_column(ForeignKey("rule_context_versions.context_version_id"), nullable=True)
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    severity: Mapped[str] = mapped_column(String, default="WARNING")
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at_utc: Mapped[str] = mapped_column(String, default="")


class RuleFindingModel(Base):
    __tablename__ = "rule_findings"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_rule_finding_fingerprint"),)

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String)
    rule_version_id: Mapped[str] = mapped_column(String)
    batch_id: Mapped[str] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_system: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[str] = mapped_column(String, default="WARNING")
    status: Mapped[str] = mapped_column(String, default="OPEN")
    title: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    updated_at_utc: Mapped[str] = mapped_column(String, default="")
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)
    acknowledged_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


def create_engine_for_sqlite(database_path: Path):
    database_path = database_path.expanduser().resolve()
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )


@event.listens_for(Engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.split(".")[0] != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def session_factory(database_path: Path):
    return sessionmaker(bind=create_engine_for_sqlite(database_path), expire_on_commit=False)


@contextmanager
def orm_session(database_path: Path) -> Iterator[Session]:
    engine = create_engine_for_sqlite(database_path)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def get_user_with_roles(session: Session, username: str) -> AppUserModel | None:
    return session.scalar(select(AppUserModel).where(AppUserModel.username == username))
#endfile
