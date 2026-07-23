from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_REVIEWER, normalize_role
from ..infrastructure.sqlite.orm import ApprovalAssignmentModel, ChangeRequestModel, orm_session


REQUEST_STATUSES = frozenset({"PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED"})
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
        item = RequestItem(str(uuid.uuid4()), now, user.username, user.computer, operation_type, entity_type, entity_id.strip(), payload, reason.strip(), "PENDING", None, None, None)
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
        roles = {normalize_role(role) for role in reviewer.roles}
        if not roles & {ROLE_REVIEWER, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN}:
            raise PermissionError("Reviewer role required.")
        with orm_session(self.database_path) as session:
            row = self._get(session, request_id)
            if row.created_by.lower() == reviewer.username.lower():
                raise PermissionError("A requester cannot approve or reject their own request.")
            if row.status not in {"PENDING", "UNDER_REVIEW"}:
                raise ValueError("Only pending requests can be decided.")
            row.status = decision
            row.reviewed_by = reviewer.username
            row.review_note = note.strip()
            row.updated_at_utc = datetime.now(timezone.utc).isoformat()
            return self._to_item(row)

    @staticmethod
    def _get(session, request_id: str) -> ChangeRequestModel:
        row = session.get(ChangeRequestModel, request_id)
        if row is None:
            raise ValueError("Request was not found.")
        return row

    @staticmethod
    def _to_item(row: ChangeRequestModel) -> RequestItem:
        return RequestItem(row.request_id, row.created_at_utc, row.created_by, row.computer_name, row.operation_type, row.entity_type, row.entity_id, json.loads(row.payload_json), row.reason, row.status, row.assigned_to, row.reviewed_by, row.review_note)
