"""
File: iam_automation/application/request_service.py
Purpose: Implements the application service for request service workflows.
Responsibilities: Exposes or coordinates: RequestItem, RequestService.
Dependencies: sqlalchemy, identity, change_request, infrastructure, publication_service
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from ..identity import CurrentUser
from ..change_request import ChangeRequest, submit_request
from ..infrastructure.sqlite.orm import ApprovalAssignmentModel, ChangeRequestModel, SystemProfileModel, orm_session
from .notification_service import NotificationService
from .publication_service import PublicationService


REQUEST_STATUSES = frozenset({"PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED"})
SLA_HOURS = {"CREATE_EMPLOYEE": 24, "UPDATE_EMPLOYEE": 16, "DEACTIVATE_EMPLOYEE": 8}
OPERATION_OPTIONS = {
    "CREATE_EMPLOYEE": "Create employee",
    "UPDATE_EMPLOYEE": "Update employee",
    "DEACTIVATE_EMPLOYEE": "Deactivate employee",
}


@dataclass(frozen=True)
class RequestItem:
    request_id: str
    created_at_utc: str
    created_by: str
    computer_name: str
    operation_type: str
    entity_type: str
    entity_id: str
    payload: dict
    reason: str
    status: str
    assigned_to: str | None
    reviewed_by: str | None
    review_note: str | None
    sla_due_at_utc: str
    sla_status: str
    expected_record_version: int = 0


class RequestService:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def list_requests(self, *, creator: str | None = None, queue: bool = False) -> list[RequestItem]:
        statement = select(ChangeRequestModel).order_by(ChangeRequestModel.created_at_utc.desc())
        if creator:
            statement = statement.where(ChangeRequestModel.created_by == creator)
        if queue:
            statement = statement.where(ChangeRequestModel.status.in_(("PENDING", "UNDER_REVIEW")))
        with orm_session(self.database_path) as session:
            return [self._to_item(row) for row in session.scalars(statement).all()]

    def export_pending_for_user(self, username: str, pending_folder: Path) -> int:
        """Export local pending work before a workspace snapshot is refreshed."""
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(ChangeRequestModel).where(ChangeRequestModel.created_by == username, ChangeRequestModel.status == "PENDING")).all()
            exported = 0
            pending_folder.mkdir(parents=True, exist_ok=True)
            for row in rows:
                if any(pending_folder.glob(f"*_{row.request_id}.json")):
                    continue
                request = ChangeRequest(
                    request_id=row.request_id,
                    created_at_utc=row.created_at_utc,
                    created_by=row.created_by,
                    computer_name=row.computer_name,
                    application_version=row.application_version,
                    operation_type=row.operation_type,
                    entity_type=row.entity_type,
                    entity_id=row.entity_id,
                    expected_record_version=row.expected_record_version,
                    payload=json.loads(row.payload_json),
                    reason=row.reason,
                    status="PENDING",
                )
                submit_request(request, pending_folder)
                exported += 1
            return exported

    def create(self, user: CurrentUser, operation_type: str, entity_id: str, payload: dict, reason: str, *, entity_type: str = "Employee") -> RequestItem:
        operation_type = operation_type.strip().upper()
        if operation_type not in OPERATION_OPTIONS:
            raise ValueError("Select a valid request operation.")
        if entity_type != "Employee":
            raise ValueError("Only Employee requests are currently supported.")
        if not entity_id.strip() or not isinstance(payload, dict) or not payload:
            raise ValueError("Employee and request details are required.")
        if not reason.strip():
            raise ValueError("A business reason is required.")
        now = datetime.now(timezone.utc).isoformat()
        due = (datetime.fromisoformat(now) + timedelta(hours=self._sla_hours().get(operation_type, 24))).isoformat()
        item = RequestItem(str(uuid.uuid4()), now, user.username, user.computer, operation_type, entity_type, entity_id.strip(), payload, reason.strip(), "PENDING", None, None, None, due, "ON_TRACK")
        with orm_session(self.database_path) as session:
            session.add(ChangeRequestModel(request_id=item.request_id, created_at_utc=now, created_by=item.created_by, computer_name=item.computer_name, application_version="local", operation_type=item.operation_type, entity_type=item.entity_type, entity_id=item.entity_id, expected_record_version=0, payload_json=json.dumps(item.payload, sort_keys=True), reason=item.reason, status=item.status, updated_at_utc=now))
        return item

    def assign(self, request_id: str, reviewer: str, assigned_by: str, reason: str) -> RequestItem:
        if not reason.strip():
            raise ValueError("Assignment reason is required.")
        with orm_session(self.database_path) as session:
            row = self._get(session, request_id)
            if row.status not in {"PENDING", "UNDER_REVIEW"}:
                raise ValueError("Only pending requests can be assigned.")
            row.status = "UNDER_REVIEW"
            row.assigned_to = reviewer
            row.updated_at_utc = datetime.now(timezone.utc).isoformat()
            session.add(ApprovalAssignmentModel(assignment_id=str(uuid.uuid4()), request_id=request_id, assigned_to=reviewer, assigned_by=assigned_by, assigned_at_utc=row.updated_at_utc, reason=reason.strip()))
            return self._to_item(row)

    def decide(self, request_id: str, reviewer: CurrentUser, decision: str, note: str) -> RequestItem:
        decision = decision.strip().upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Decision must be Approved or Rejected.")
        if not note.strip():
            raise ValueError("A review note is required.")
        if not reviewer.can_decide_requests:
            raise PermissionError("Administrator approval is required to decide requests.")
        with orm_session(self.database_path) as session:
            row = self._get(session, request_id)
            if row.status not in {"PENDING", "UNDER_REVIEW"}:
                raise ValueError("Only pending requests can be decided.")
            row.status = decision
            row.reviewed_by = reviewer.username
            row.review_note = note.strip()
            row.updated_at_utc = datetime.now(timezone.utc).isoformat()
            if decision == "APPROVED":
                PublicationService(self.database_path).enqueue(row.request_id, reviewer.username)
            return self._to_item(row)

    def reassign_for_delegation(self, principal: str, delegate: str, assigned_by: str, reason: str) -> int:
        count = 0
        notifications: list[tuple[str, str]] = []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(ChangeRequestModel).where(ChangeRequestModel.status.in_(("PENDING", "UNDER_REVIEW")), (ChangeRequestModel.assigned_to.is_(None)) | (ChangeRequestModel.assigned_to == principal))).all()
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                row.status = "UNDER_REVIEW"
                row.assigned_to = delegate
                row.updated_at_utc = now
                session.add(ApprovalAssignmentModel(assignment_id=str(uuid.uuid4()), request_id=row.request_id, assigned_to=delegate, assigned_by=assigned_by, assigned_at_utc=now, reason=reason))
                notifications.append((row.created_by, row.request_id))
                count += 1
        notification_service = NotificationService(self.database_path)
        for recipient, reassigned_request_id in notifications:
            notification_service.create(
                recipient,
                "REQUEST_REASSIGNED",
                "Request reassigned",
                f"Request {reassigned_request_id[:8]} was reassigned for approval coverage.",
                severity="WARNING",
                target_route="/admin/approvals",
                entity_type="change_request",
                entity_id=reassigned_request_id,
                notification_id=hashlib.sha256(f"request-reassigned:{recipient.casefold()}:{reassigned_request_id}:{delegate}".encode("utf-8")).hexdigest(),
            )
        return count

    def escalate_overdue(self, recipients: tuple[str, ...]) -> int:
        count = 0
        now = datetime.now(timezone.utc)
        notifications: list[tuple[str, str]] = []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(ChangeRequestModel).where(ChangeRequestModel.status.in_(("PENDING", "UNDER_REVIEW")))).all()
            for row in rows:
                due = datetime.fromisoformat(row.created_at_utc) + timedelta(hours=self._sla_hours().get(row.operation_type, 24))
                if due < now:
                    for recipient in recipients:
                        notifications.append((recipient, row.request_id))
                    row.status = "UNDER_REVIEW"
                    row.updated_at_utc = now.isoformat()
                    count += 1
        notification_service = NotificationService(self.database_path)
        for recipient, overdue_request_id in notifications:
            notification_service.create(
                recipient,
                "SLA_BREACH",
                "Approval SLA breached",
                f"Request {overdue_request_id[:8]} is overdue for review.",
                severity="CRITICAL",
                target_route="/admin/approvals",
                entity_type="change_request",
                entity_id=overdue_request_id,
                notification_id=hashlib.sha256(f"sla-breach:{recipient.casefold()}:{overdue_request_id}".encode("utf-8")).hexdigest(),
            )
        return count

    @staticmethod
    def _get(session, request_id: str) -> ChangeRequestModel:
        row = session.get(ChangeRequestModel, request_id)
        if row is None:
            raise ValueError("Request was not found.")
        return row

    def _sla_hours(self) -> dict[str, int]:
        with orm_session(self.database_path) as session:
            profile = session.get(SystemProfileModel, "global_settings")
            if not profile:
                return SLA_HOURS
            try:
                configured = json.loads(profile.profile_json).get("approval_sla_hours", {})
                return {**SLA_HOURS, **{key: max(1, int(value)) for key, value in configured.items()}}
            except (TypeError, ValueError, json.JSONDecodeError):
                return SLA_HOURS

    def _to_item(self, row: ChangeRequestModel) -> RequestItem:
        due = datetime.fromisoformat(row.created_at_utc) + timedelta(hours=self._sla_hours().get(row.operation_type, 24))
        sla_status = "OVERDUE" if due < datetime.now(timezone.utc) and row.status in {"PENDING", "UNDER_REVIEW"} else "ON_TRACK"
        return RequestItem(row.request_id, row.created_at_utc, row.created_by, row.computer_name, row.operation_type, row.entity_type, row.entity_id, json.loads(row.payload_json), row.reason, row.status, row.assigned_to, row.reviewed_by, row.review_note, due.isoformat(), sla_status, row.expected_record_version)
#endfile
