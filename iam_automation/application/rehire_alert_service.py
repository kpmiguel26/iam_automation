"""
File: iam_automation/application/rehire_alert_service.py
Purpose: Implements the application service for rehire alert service workflows.
Responsibilities: Exposes or coordinates: RehireAlertService.
Dependencies: sqlalchemy, infrastructure, business_calendar, publication_state, source_date
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import IngestionRecordModel, WorkerModel, orm_session
from .business_calendar import business_days_between, configured_rehire_holidays
from .publication_state import mark_publication_pending
from .source_date import parse_source_date
from .status_catalog import is_inactive_source_status, normalize_accessnow_status


class RehireAlertService:
    """Evaluate and archive the 30-business-day rehire validation."""

    _PENDING_STATUSES = ("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS", "LINKED", "CURRENT")

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _source_file_name(value: object) -> str:
        return Path(str(value or "").replace("\\", "/")).name

    @staticmethod
    def _alert_date(value: object) -> date | None:
        return parse_source_date(value)

    @staticmethod
    def _business_days_between(start: date, end: date) -> int:
        return business_days_between(start, end, configured_rehire_holidays())

    @staticmethod
    def _candidate_keys(payload: dict[str, object], source_record_key: str = "") -> set[str]:
        keys: set[str] = set()
        for field in ("accessnow_employee_id", "accessnow_nuid", "vendor_employee_id", "supplier_reference", "worker_id", "buyer_reference"):
            value = str(payload.get(field) or "").strip().casefold()
            if value:
                keys.add(f"id:{value}")
        email = str(payload.get("email") or payload.get("vendor_email") or payload.get("vendor_email_address") or "").strip().casefold()
        if email:
            keys.add(f"email:{email}")
        first = str(payload.get("first_name") or payload.get("employee_first_name") or "").strip().casefold()
        last = str(payload.get("last_name") or payload.get("employee_last_name") or "").strip().casefold()
        if first and last:
            keys.add(f"name:{first}:{last}")
        return keys

    def list_alerts(self, source_file: str = "") -> list[dict[str, object]]:
        selected_file = self._source_file_name(source_file) if source_file else ""
        with orm_session(self.database_path) as session:
            roster_rows = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == "ROSTER_LOCK",
                IngestionRecordModel.status.in_(self._PENDING_STATUSES),
                IngestionRecordModel.observation_state.not_in(("SUPERSEDED", "RESOLVED")),
            ).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            access_rows = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == "ACCESSNOW",
                IngestionRecordModel.status.in_(self._PENDING_STATUSES + ("APPLIED",)),
                IngestionRecordModel.observation_state.not_in(("SUPERSEDED", "RESOLVED")),
            ).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            workers = {worker.worker_id: worker.display_name for worker in session.scalars(select(WorkerModel)).all()}

            parsed_access: list[tuple[IngestionRecordModel, dict[str, object]]] = []
            for row in access_rows:
                try:
                    payload = json.loads(row.normalized_json or "{}")
                except json.JSONDecodeError:
                    payload = {}
                status = normalize_accessnow_status(payload.get("accessnow_status"))
                if is_inactive_source_status(status):
                    parsed_access.append((row, payload))

            access_by_worker: dict[str, list[tuple[IngestionRecordModel, dict[str, object]]]] = {}
            access_by_key: dict[str, list[tuple[IngestionRecordModel, dict[str, object]]]] = {}
            for access, payload in parsed_access:
                if access.matched_worker_id:
                    access_by_worker.setdefault(access.matched_worker_id, []).append((access, payload))
                for key in self._candidate_keys(payload, access.source_record_key):
                    access_by_key.setdefault(key, []).append((access, payload))

            alerts: list[dict[str, object]] = []
            for roster in roster_rows:
                if selected_file and self._source_file_name(roster.source_file) != selected_file:
                    continue
                try:
                    roster_payload = json.loads(roster.normalized_json or "{}")
                except json.JSONDecodeError:
                    roster_payload = {}
                matches: list[tuple[IngestionRecordModel, dict[str, object]]] = []
                if roster.matched_worker_id:
                    matches.extend(access_by_worker.get(roster.matched_worker_id, ()))
                for key in self._candidate_keys(roster_payload, roster.source_record_key):
                    matches.extend(access_by_key.get(key, ()))
                if len(matches) > 1:
                    seen_access_ids: set[str] = set()
                    matches = [item for item in matches if not (item[0].record_id in seen_access_ids or seen_access_ids.add(item[0].record_id))]
                if not matches:
                    continue
                access, access_payload = matches[0]
                status = normalize_accessnow_status(access_payload.get("accessnow_status") or "TERMINATED")
                termination_date = next((self._alert_date(access_payload.get(key)) for key in ("terminated_date", "deactivated_date", "termination_date", "end_date", "production_start_date") if self._alert_date(access_payload.get(key))), None)
                roster_date = next((self._alert_date(roster_payload.get(key)) for key in ("onboarding_date", "worker_start_date", "start_date", "hire_date") if self._alert_date(roster_payload.get(key))), None)
                termination_date = termination_date or self._alert_date(access.created_at_utc)
                roster_date = roster_date or self._alert_date(roster.created_at_utc)
                if not termination_date or not roster_date:
                    continue
                elapsed = self._business_days_between(termination_date, roster_date)
                if elapsed < 0 or elapsed > 30:
                    continue
                worker_id = str(roster.matched_worker_id or access.matched_worker_id or "")
                fallback_name = " ".join(str(roster_payload.get(key) or "").strip() for key in ("first_name", "last_name") if str(roster_payload.get(key) or "").strip())
                alerts.append({
                    "alert_id": f"{roster.record_id}:{access.record_id}",
                    "record_id": roster.record_id,
                    "access_record_id": access.record_id,
                    "worker_id": worker_id,
                    "worker_name": workers.get(worker_id) or fallback_name or "Unnamed employee",
                    "status": status,
                    "source_file": self._source_file_name(roster.source_file),
                    "source_record_key": roster.source_record_key,
                    "terminated_on": termination_date.isoformat(),
                    "proposed_start_on": roster_date.isoformat(),
                    "business_days_elapsed": elapsed,
                    "business_days_remaining": max(0, 30 - elapsed),
                })
            return alerts

    def count(self) -> int:
        return len(self.list_alerts())

    def list_for_worker(self, worker_id: str) -> list[dict[str, object]]:
        return [item for item in self.list_alerts() if str(item.get("worker_id", "")) == worker_id]

    def archive(self, record_id: str, actor: str, reason: str) -> dict[str, str]:
        record_id = str(record_id).strip()
        reason = str(reason).strip()
        if not record_id:
            raise ValueError("A Roster Lock record is required.")
        if not reason:
            raise ValueError("A reason is required to archive a rehire alert.")
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            record = session.get(IngestionRecordModel, record_id)
            if record is None or record.source_system != "ROSTER_LOCK":
                raise ValueError("The rehire alert source record was not found.")
            if record.observation_state == "RESOLVED":
                return {"record_id": record_id, "status": "RESOLVED"}
            record.observation_state = "RESOLVED"
            record.last_seen_at_utc = now
            session.commit()
        mark_publication_pending(self.database_path, actor=actor, reason=f"Rehire alert archived: {reason}")
        return {"record_id": record_id, "status": "RESOLVED"}
