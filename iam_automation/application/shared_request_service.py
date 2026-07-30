from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..change_request import ChangeRequest, load_request_file, new_request, submit_request
from ..identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN, ROLE_REVIEWER, ROLE_SUPER_OPERATOR, normalize_role
from .request_service import RequestItem, SLA_HOURS


WORKFLOW_FOLDERS = {
    "PENDING": "pending",
    "UNDER_REVIEW": "under_review",
    "APPROVED": "approved",
    "REJECTED": "rejected",
}


class SharedRequestService:
    """Workflow for requests whose source of truth is SharePoint JSON."""

    def __init__(self, sharepoint_root: Path):
        self.sharepoint_root = sharepoint_root
        self.requests_root = sharepoint_root / "requests"

    def create(self, user: CurrentUser, operation_type: str, entity_id: str, payload: dict, reason: str) -> ChangeRequest:
        request = new_request(
            user=user,
            application_version="local",
            operation_type=operation_type.strip().upper(),
            entity_type="ImportBatch" if operation_type.strip().upper() in {"IMPORT_ROSTER_LOCK", "IMPORT_RSR_SUPPLIER_DETAILS"} else "Employee",
            entity_id=entity_id.strip(),
            expected_record_version=0,
            payload=payload,
            reason=reason,
        )
        submit_request(request, self._folder("PENDING"))
        return request

    def list_requests(self, *, creator: str | None = None, queue: bool = False) -> list[RequestItem]:
        items: list[RequestItem] = []
        for request in self._load_all():
            if creator and request.created_by.lower() != creator.lower():
                continue
            if queue and request.status not in {"PENDING", "UNDER_REVIEW"}:
                continue
            items.append(self._to_item(request))
        return sorted(items, key=lambda item: item.created_at_utc, reverse=True)

    def list_approved(self) -> list[RequestItem]:
        return [item for item in self.list_requests() if item.status == "APPROVED"]

    def assign(self, request_id: str, reviewer: str, assigned_by: str, reason: str) -> RequestItem:
        if not reviewer.strip():
            raise ValueError("A reviewer is required.")
        if not reason.strip():
            raise ValueError("Assignment reason is required.")
        path, request = self._find(request_id)
        if request.status not in {"PENDING", "UNDER_REVIEW"}:
            raise ValueError("Only pending requests can be assigned.")
        updated = self._updated(request, status="UNDER_REVIEW", assigned_to=reviewer.strip(), updated_at_utc=self._now())
        self._move(path, updated)
        return self._to_item(updated)

    def decide(self, request_id: str, reviewer: CurrentUser, decision: str, note: str) -> tuple[RequestItem, bool]:
        decision = decision.strip().upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Decision must be Approved or Rejected.")
        if decision == "REJECTED" and not note.strip():
            raise ValueError("A rejection reason is required.")
        if decision == "APPROVED" and not note.strip():
            raise ValueError("An approval note is required.")
        roles = {normalize_role(role) for role in reviewer.roles}
        if not roles - {"REQUESTER"}:
            raise PermissionError("A requester-only account cannot approve requests.")
        path, request = self._find(request_id)
        self_approval = request.created_by.lower() == reviewer.username.lower()
        if self_approval and ROLE_SUPER_OPERATOR not in roles:
            raise PermissionError("A requester cannot approve or reject their own request.")
        updated = self._updated(
            request,
            status=decision,
            reviewed_by=reviewer.username,
            review_note=note.strip(),
            updated_at_utc=self._now(),
        )
        self._move(path, updated)
        return self._to_item(updated), self_approval

    def reassign_for_delegation(self, principal: str, delegate: str, reason: str) -> int:
        count = 0
        for request in self._load_all():
            if request.status not in {"PENDING", "UNDER_REVIEW"} or (request.assigned_to and request.assigned_to.lower() != principal.lower()):
                continue
            path, _ = self._find(request.request_id)
            self._move(path, self._updated(request, status="UNDER_REVIEW", assigned_to=delegate, updated_at_utc=self._now()))
            count += 1
        return count

    def escalate_overdue(self, recipients: tuple[str, ...]) -> int:
        """Return overdue count without changing the shared JSON workflow."""
        return sum(1 for item in self.list_requests(queue=True) if item.sla_status == "OVERDUE")

    def _load_all(self) -> list[ChangeRequest]:
        requests: list[ChangeRequest] = []
        for folder in WORKFLOW_FOLDERS.values():
            root = self.requests_root / folder
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.json")):
                try:
                    requests.append(load_request_file(path))
                except ValueError:
                    # Invalid files remain visible to the import/quarantine flow.
                    continue
        return requests

    def _find(self, request_id: str) -> tuple[Path, ChangeRequest]:
        for folder in WORKFLOW_FOLDERS.values():
            root = self.requests_root / folder
            for path in root.glob(f"*_{request_id}.json") if root.is_dir() else ():
                return path, load_request_file(path)
        raise ValueError("Request was not found in the shared workspace.")

    def _folder(self, status: str) -> Path:
        folder = self.requests_root / WORKFLOW_FOLDERS[status]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _move(self, path: Path, request: ChangeRequest) -> Path:
        destination = self._folder(request.status) / path.name
        self._atomic_write(destination, request)
        if path != destination and path.exists():
            path.unlink()
        return destination

    @staticmethod
    def _atomic_write(path: Path, request: ChangeRequest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(request), handle, indent=2, sort_keys=True)
                handle.write("\n")
            Path(temp_name).replace(path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _updated(request: ChangeRequest, **changes) -> ChangeRequest:
        values = asdict(request)
        values.update(changes)
        return ChangeRequest(**values)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_item(request: ChangeRequest) -> RequestItem:
        created = datetime.fromisoformat(request.created_at_utc.replace("Z", "+00:00"))
        due = created + timedelta(hours=SLA_HOURS.get(request.operation_type, 24))
        now = datetime.now(timezone.utc)
        return RequestItem(
            request_id=request.request_id,
            created_at_utc=request.created_at_utc,
            created_by=request.created_by,
            computer_name=request.computer_name,
            operation_type=request.operation_type,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            payload=request.payload,
            reason=request.reason,
            status=request.status,
            assigned_to=request.assigned_to,
            reviewed_by=request.reviewed_by,
            review_note=request.review_note,
            sla_due_at_utc=due.isoformat(),
            sla_status="OVERDUE" if due < now else "ON_TRACK",
            expected_record_version=request.expected_record_version,
        )
