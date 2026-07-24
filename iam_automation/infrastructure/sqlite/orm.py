from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, create_engine, select
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


class NotificationModel(Base):
    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String, primary_key=True)
    recipient_username: Mapped[str] = mapped_column(String)
    notification_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="INFO")
    title: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String, default="")
    entity_id: Mapped[str] = mapped_column(String, default="")
    target_route: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="UNREAD")
    created_at_utc: Mapped[str] = mapped_column(String, default="")
    read_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at_utc: Mapped[str | None] = mapped_column(String, nullable=True)


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
    created_by: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String, default="")
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


class SystemProfileModel(Base):
    __tablename__ = "system_profiles"

    profile_name: Mapped[str] = mapped_column(String, primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


def create_engine_for_sqlite(database_path: Path):
    database_path = database_path.expanduser().resolve()
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )


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
