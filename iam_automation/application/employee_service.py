from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select

from ..infrastructure.sqlite.orm import (
    IngestionRecordModel,
    WorkerDiscrepancyModel,
    WorkerEngagementModel,
    WorkerIdentifierModel,
    WorkerModel,
    WorkerMergeEventModel,
    WorkerProfileVersionModel,
    WorkerSourceProfileModel,
    WorkerSourceLineageModel,
    orm_session,
)
from .worker_history_service import record_worker_version, version_dict
from .publication_state import mark_publication_pending
from .source_reconciliation import ensure_source_identifiers, find_worker_matches
from .business_calendar import business_days_between, configured_rehire_holidays
from .source_date import parse_source_date
from .status_catalog import is_inactive_source_status, normalize_accessnow_status


@dataclass(frozen=True)
class EmployeeSummary:
    worker_id: str
    display_name: str
    email: str
    status: str
    identifier: str
    vendor_name: str
    job_title: str
    source_system: str
    discrepancy_count: int


class EmployeeService:
    """Read canonical workers and explicitly promote staged source records."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _source_file_name(value: object) -> str:
        """Return a portable basename for records created on any OS."""
        return Path(str(value or "").replace("\\", "/")).name

    def _pending_source_records(self, source_file: str = "") -> list[IngestionRecordModel]:
        """Load pending source records, optionally scoped to one workbook."""
        pending_statuses = ("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS", "LINKED", "CURRENT")
        selected_file = self._source_file_name(source_file) if source_file else ""
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.status.in_(pending_statuses),
                IngestionRecordModel.observation_state.not_in(("SUPERSEDED", "RESOLVED")),
            )).all()
        if not selected_file:
            return records
        return [record for record in records if self._source_file_name(record.source_file) == selected_file]

    def list_workers(self, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "", review: str = "") -> list[EmployeeSummary]:
        """Return the full directory for internal callers and small datasets."""
        workers, _ = self.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, review=review, page=1, per_page=None)
        return workers

    def list_workers_page(self, *, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "", review: str = "", page: int = 1, per_page: int | None = 25) -> tuple[list[EmployeeSummary], int]:
        """Query only one directory page; filtering stays in SQLite."""
        search = search.strip()
        engagement = engagement.strip()
        page = max(1, int(page))
        if per_page is not None:
            per_page = max(1, min(int(per_page), 100))
        with orm_session(self.database_path) as session:
            filters = []
            if status == "NON_ACTIVE":
                filters.append(WorkerModel.status != "ACTIVE")
            elif status != "ALL":
                filters.append(WorkerModel.status == status)
            if vendor == "NONE":
                filters.append(~select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, func.trim(WorkerEngagementModel.vendor_name) != "").exists())
            elif vendor != "ALL":
                filters.append(select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, WorkerEngagementModel.vendor_name == vendor).exists())
            if source != "ALL":
                filters.append(select(WorkerIdentifierModel.worker_id).where(WorkerIdentifierModel.worker_id == WorkerModel.worker_id, WorkerIdentifierModel.source_system == source, WorkerIdentifierModel.active.is_(True)).exists())
            if review == "OPEN":
                filters.append(select(WorkerDiscrepancyModel.worker_id).where(WorkerDiscrepancyModel.worker_id == WorkerModel.worker_id, WorkerDiscrepancyModel.status == "OPEN").exists())
            if engagement:
                engagement_pattern = f"%{engagement}%"
                filters.append(select(WorkerEngagementModel.worker_id).where(
                    WorkerEngagementModel.worker_id == WorkerModel.worker_id,
                    or_(
                        WorkerEngagementModel.vendor_name.ilike(engagement_pattern),
                        WorkerEngagementModel.program.ilike(engagement_pattern),
                        WorkerEngagementModel.project.ilike(engagement_pattern),
                        WorkerEngagementModel.lob.ilike(engagement_pattern),
                        WorkerEngagementModel.job_title.ilike(engagement_pattern),
                        WorkerEngagementModel.country.ilike(engagement_pattern),
                        WorkerEngagementModel.site_location.ilike(engagement_pattern),
                        WorkerEngagementModel.statement_of_work.ilike(engagement_pattern),
                    ),
                ).exists())
            if search:
                pattern = f"%{search}%"
                filters.append(or_(
                    WorkerModel.display_name.ilike(pattern),
                    WorkerModel.canonical_email.ilike(pattern),
                    select(WorkerIdentifierModel.worker_id).where(WorkerIdentifierModel.worker_id == WorkerModel.worker_id, WorkerIdentifierModel.identifier_value.ilike(pattern)).exists(),
                    select(WorkerEngagementModel.worker_id).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id, or_(WorkerEngagementModel.vendor_name.ilike(pattern), WorkerEngagementModel.job_title.ilike(pattern))).exists(),
                ))
            filters.append(WorkerModel.superseded_by_worker_id.is_(None))
            statement = select(WorkerModel).where(*filters).order_by(WorkerModel.display_name, WorkerModel.worker_id)
            total = int(session.scalar(select(func.count()).select_from(WorkerModel).where(*filters)) or 0)
            if per_page is not None:
                statement = statement.offset((page - 1) * per_page).limit(per_page)
            workers = session.scalars(statement).all()
            result: list[EmployeeSummary] = []
            for worker in workers:
                engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker.worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
                identifier = session.scalar(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker.worker_id, WorkerIdentifierModel.active.is_(True)).order_by(WorkerIdentifierModel.created_at_utc))
                discrepancy_count = session.scalar(select(func.count()).select_from(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id == worker.worker_id, WorkerDiscrepancyModel.status == "OPEN")) or 0
                result.append(EmployeeSummary(worker.worker_id, worker.display_name, worker.canonical_email, worker.status, identifier.identifier_value if identifier else "", engagement.vendor_name if engagement else "", engagement.job_title if engagement else "", identifier.source_system if identifier else "", int(discrepancy_count)))
            return result, total

    def filter_values(self) -> tuple[list[str], list[str], list[str]]:
        with orm_session(self.database_path) as session:
            statuses = sorted({value for value in session.scalars(select(WorkerModel.status)).all() if value})
            vendors = sorted({value for value in session.scalars(select(WorkerEngagementModel.vendor_name)).all() if value})
            sources = sorted({value for value in session.scalars(select(WorkerIdentifierModel.source_system).where(WorkerIdentifierModel.active.is_(True))).all() if value})
            return statuses, vendors, sources

    def list_staged_records(self) -> list[dict[str, str]]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS"))).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            return [{"record_id": row.record_id, "batch_id": row.batch_id, "source_system": row.source_system, "source_record_key": row.source_record_key, "source_file": self._source_file_name(row.source_file), "status": row.status, "match_status": row.match_status, "matched_worker_id": row.matched_worker_id or "", "match_reason": row.match_reason, "payload": json.loads(row.normalized_json)} for row in rows]

    def pending_source_update_count(self) -> int:
        """Count staged source rows without loading their payloads."""
        with orm_session(self.database_path) as session:
            return int(session.scalar(select(func.count()).select_from(IngestionRecordModel).where(
                IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS")),
            )) or 0)

    @staticmethod
    def _alert_date(value: object) -> date | None:
        """Parse the date formats used by AccessNow and Roster Lock exports."""
        return parse_source_date(value)

    @staticmethod
    def _business_days_between(start: date, end: date) -> int:
        """Count configured business days after status through proposed hire."""
        return business_days_between(start, end, configured_rehire_holidays())

    def rehire_alerts(self, source_file: str = "") -> list[dict[str, object]]:
        """Find pending Roster Lock rows inside the 30-business-day rehire hold.

        Alerts are critical evidence for the approval workflow, not a reason
        to discard or prevent submission of the management decision.
        """
        pending_statuses = ("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS", "LINKED", "CURRENT")
        selected_file = self._source_file_name(source_file) if source_file else ""
        with orm_session(self.database_path) as session:
            roster_rows = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == "ROSTER_LOCK",
                IngestionRecordModel.status.in_(pending_statuses),
                IngestionRecordModel.observation_state.not_in(("SUPERSEDED", "RESOLVED")),
            ).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            access_rows = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.source_system == "ACCESSNOW",
                IngestionRecordModel.status.in_(pending_statuses + ("APPLIED",)),
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
            for item in parsed_access:
                access, payload = item
                if access.matched_worker_id:
                    access_by_worker.setdefault(access.matched_worker_id, []).append(item)
                for key in self._candidate_keys(payload, access.source_record_key):
                    access_by_key.setdefault(key, []).append(item)

            alerts: list[dict[str, object]] = []
            for roster in roster_rows:
                if selected_file and self._source_file_name(roster.source_file) != selected_file:
                    continue
                try:
                    roster_payload = json.loads(roster.normalized_json or "{}")
                except json.JSONDecodeError:
                    roster_payload = {}
                roster_keys = self._candidate_keys(roster_payload, roster.source_record_key)
                matches: list[tuple[IngestionRecordModel, dict[str, object]]] = []
                if roster.matched_worker_id:
                    matches.extend(access_by_worker.get(roster.matched_worker_id, ()))
                for key in roster_keys:
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

    def rehire_alert_count(self) -> int:
        return len(self.rehire_alerts())

    def rehire_alerts_for_worker(self, worker_id: str) -> list[dict[str, object]]:
        return [item for item in self.rehire_alerts() if str(item.get("worker_id", "")) == worker_id]

    def resolve_rehire_alert(self, record_id: str, actor: str, reason: str) -> dict[str, str]:
        """Archive a reviewed alert without changing source evidence or worker status."""
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

    @staticmethod
    def _source_label(source_system: str) -> str:
        return str(source_system or "Unknown source").replace("_", " ").title()

    @staticmethod
    def _source_file_name(value: object) -> str:
        """Return a portable basename for records created on any OS."""
        return Path(str(value or "").replace("\\", "/")).name

    def list_source_systems(self) -> list[dict[str, object]]:
        """Return lightweight source-level counters without loading payload JSON."""
        with orm_session(self.database_path) as session:
            rows = session.execute(
                select(
                    IngestionRecordModel.source_system,
                    IngestionRecordModel.source_file,
                    IngestionRecordModel.status,
                    IngestionRecordModel.match_status,
                    IngestionRecordModel.observation_state,
                    IngestionRecordModel.created_at_utc,
                ).order_by(IngestionRecordModel.created_at_utc.desc())
            ).all()
        grouped: dict[str, dict[str, object]] = {}
        for source_system, source_file, status, match_status, observation_state, created_at in rows:
            item = grouped.setdefault(str(source_system), {
                "source_system": str(source_system),
                "label": self._source_label(str(source_system)),
                "file_count": 0,
                "record_count": 0,
                "pending_count": 0,
                "linked_count": 0,
                "ambiguous_count": 0,
                "conflict_count": 0,
                "superseded_count": 0,
                "latest_at": "",
                "files": set(),
            })
            files = item["files"]
            if isinstance(files, set):
                files.add(self._source_file_name(source_file))
                item["file_count"] = len(files)
            item["record_count"] = int(item["record_count"]) + 1
            state = str(observation_state or "")
            if state == "SUPERSEDED":
                item["superseded_count"] = int(item["superseded_count"]) + 1
            elif str(match_status) == "AMBIGUOUS":
                item["ambiguous_count"] = int(item["ambiguous_count"]) + 1
            elif str(match_status) == "CONFLICT":
                item["conflict_count"] = int(item["conflict_count"]) + 1
            elif state in {"CURRENT", "LINKED"} or str(status) in {"APPLIED", "LINKED", "CURRENT"}:
                item["linked_count"] = int(item["linked_count"]) + 1
            elif str(status) not in {"QUARANTINED"}:
                item["pending_count"] = int(item["pending_count"]) + 1
            if not item["latest_at"]:
                item["latest_at"] = str(created_at or "")
        for item in grouped.values():
            item.pop("files", None)
        return sorted(grouped.values(), key=lambda item: str(item["label"]))

    def list_source_files(self, source_system: str) -> list[dict[str, object]]:
        """Return file summaries using columns only; payloads are not read."""
        with orm_session(self.database_path) as session:
            rows = session.execute(
                select(
                    IngestionRecordModel.source_file,
                    IngestionRecordModel.source_checksum,
                    IngestionRecordModel.status,
                    IngestionRecordModel.match_status,
                    IngestionRecordModel.observation_state,
                    IngestionRecordModel.created_at_utc,
                ).where(IngestionRecordModel.source_system == source_system)
                .order_by(IngestionRecordModel.created_at_utc.desc())
            ).all()
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for source_file, checksum, status, match_status, observation_state, created_at in rows:
            key = (self._source_file_name(source_file), str(checksum or ""))
            item = grouped.setdefault(key, {
                "source_system": source_system,
                "source_file": key[0],
                "source_path": str(source_file or ""),
                "source_checksum": key[1],
                "record_count": 0,
                "pending_count": 0,
                "linked_count": 0,
                "ambiguous_count": 0,
                "conflict_count": 0,
                "superseded_count": 0,
                "latest_at": str(created_at or ""),
            })
            item["record_count"] = int(item["record_count"]) + 1
            state = str(observation_state or "")
            if state == "SUPERSEDED":
                item["superseded_count"] = int(item["superseded_count"]) + 1
            elif str(match_status) == "AMBIGUOUS":
                item["ambiguous_count"] = int(item["ambiguous_count"]) + 1
            elif str(match_status) == "CONFLICT":
                item["conflict_count"] = int(item["conflict_count"]) + 1
            elif state in {"CURRENT", "LINKED"} or str(status) in {"APPLIED", "LINKED", "CURRENT"}:
                item["linked_count"] = int(item["linked_count"]) + 1
            elif str(status) != "QUARANTINED":
                item["pending_count"] = int(item["pending_count"]) + 1
        return list(grouped.values())

    def get_source_file_summary(self, source_system: str, source_file: str) -> dict[str, object] | None:
        files = self.list_source_files(source_system)
        return next((item for item in files if item["source_file"] == self._source_file_name(source_file)), None)

    def list_source_records(self, source_system: str, source_file: str, *, page: int = 1, per_page: int = 50) -> tuple[list[dict[str, object]], int]:
        """Return one page of source rows and deserialize only that page."""
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), 100))
        file_summary = self.get_source_file_summary(source_system, source_file)
        if file_summary is None:
            return [], 0
        source_path = str(file_summary["source_path"])
        with orm_session(self.database_path) as session:
            total = int(session.scalar(select(func.count()).select_from(IngestionRecordModel).where(
                IngestionRecordModel.source_system == source_system,
                IngestionRecordModel.source_file == source_path,
            )) or 0)
            rows = session.execute(
                select(
                    IngestionRecordModel.record_id,
                    IngestionRecordModel.batch_id,
                    IngestionRecordModel.source_system,
                    IngestionRecordModel.source_record_key,
                    IngestionRecordModel.status,
                    IngestionRecordModel.match_status,
                    IngestionRecordModel.match_reason,
                    IngestionRecordModel.matched_worker_id,
                    IngestionRecordModel.observation_state,
                    IngestionRecordModel.created_at_utc,
                    IngestionRecordModel.source_file,
                ).where(IngestionRecordModel.source_system == source_system, IngestionRecordModel.source_file == source_path)
                .order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)
                .offset((page - 1) * per_page).limit(per_page)
            ).all()
        page_rows = rows
        record_ids = [str(row[0]) for row in page_rows]
        payloads = {}
        if record_ids:
            with orm_session(self.database_path) as session:
                payloads = dict(session.execute(
                    select(IngestionRecordModel.record_id, IngestionRecordModel.normalized_json)
                    .where(IngestionRecordModel.record_id.in_(record_ids))
                ).all())
        result = []
        worker_ids = {str(row[7]) for row in page_rows if row[7]}
        workers = {}
        if worker_ids:
            with orm_session(self.database_path) as session:
                workers = {worker.worker_id: worker.display_name for worker in session.scalars(select(WorkerModel).where(WorkerModel.worker_id.in_(worker_ids))).all()}
        for row in page_rows:
            try:
                payload = json.loads(payloads.get(str(row[0]), "{}") or "{}")
            except json.JSONDecodeError:
                payload = {}
            result.append({
                "record_id": row[0], "batch_id": row[1], "source_system": row[2],
                "source_record_key": row[3], "worker_name": workers.get(row[7], ""),
                "status": row[4], "match_status": row[5], "match_reason": row[6],
                "matched_worker_id": row[7] or "", "observation_state": row[8] or "PENDING",
                "created_at_utc": row[9], "payload": payload,
            })
        return result, total

    def link_source_record(self, record_id: str, worker_id: str, actor: str = "system") -> dict[str, object]:
        """Link one immutable source observation and make it current for its key."""
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            record = session.get(IngestionRecordModel, record_id)
            worker = session.get(WorkerModel, worker_id)
            if record is None or worker is None:
                raise ValueError("Source record or canonical employee was not found.")
            self._supersede_previous_source_record_in_session(session, record, now)
            record.matched_worker_id = worker_id
            record.match_status = "MATCHED"
            record.status = "LINKED"
            record.observation_state = "CURRENT"
            record.linked_at_utc = now
            record.last_seen_at_utc = now
            self._upsert_source_profile(session, record, worker_id, now)
            session.commit()
        return {"record_id": record_id, "worker_id": worker_id, "actor": actor, "state": "CURRENT"}

    def supersede_previous_source_record(self, record_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            record = session.get(IngestionRecordModel, record_id)
            if record is None:
                raise ValueError("Source record was not found.")
            count = self._supersede_previous_source_record_in_session(session, record, now)
            session.commit()
            return count

    @staticmethod
    def _supersede_previous_source_record_in_session(session, record: IngestionRecordModel, now: str) -> int:
        previous = session.scalars(select(IngestionRecordModel).where(
            IngestionRecordModel.source_system == record.source_system,
            IngestionRecordModel.source_record_key == record.source_record_key,
            IngestionRecordModel.record_id != record.record_id,
            IngestionRecordModel.created_at_utc < record.created_at_utc,
            IngestionRecordModel.observation_state != "SUPERSEDED",
        )).all()
        for item in previous:
            item.observation_state = "SUPERSEDED"
            item.superseded_by_record_id = record.record_id
            item.last_seen_at_utc = now
        return len(previous)

    @staticmethod
    def _upsert_source_profile(session, record: IngestionRecordModel, worker_id: str, now: str) -> None:
        profile = session.scalar(select(WorkerSourceProfileModel).where(
            WorkerSourceProfileModel.source_system == record.source_system,
            WorkerSourceProfileModel.source_record_key == record.source_record_key,
        ))
        if profile is None:
            profile = WorkerSourceProfileModel(
                profile_id=str(uuid.uuid4()), worker_id=worker_id, source_system=record.source_system,
                source_record_key=record.source_record_key, first_seen_at_utc=record.created_at_utc or now,
            )
            session.add(profile)
        profile.worker_id = worker_id
        profile.current_record_id = record.record_id
        profile.snapshot_json = record.normalized_json
        profile.status = "CURRENT"
        profile.last_seen_at_utc = now

    @staticmethod
    def _record_source_lineage_in_session(session, record: IngestionRecordModel, worker_id: str, now: str) -> None:
        """Attach every field in an immutable source row to the employee once."""
        payload = json.loads(record.normalized_json or "{}")
        existing = {
            (item.source_file, item.row_number, item.field_name)
            for item in session.scalars(select(WorkerSourceLineageModel).where(
                WorkerSourceLineageModel.worker_id == worker_id,
                WorkerSourceLineageModel.source_system == record.source_system,
                WorkerSourceLineageModel.source_file == record.source_file,
                WorkerSourceLineageModel.row_number == record.row_number,
            )).all()
        }
        for field_name, value in payload.items():
            if (record.source_file, record.row_number, field_name) in existing:
                continue
            session.add(WorkerSourceLineageModel(
                lineage_id=str(uuid.uuid4()), worker_id=worker_id, engagement_id=None,
                batch_id=record.batch_id, source_system=record.source_system,
                source_file=record.source_file, source_checksum=record.source_checksum,
                row_number=record.row_number, field_name=field_name,
                raw_value=str(value or ""), normalized_value=str(value or ""), observed_at_utc=now,
            ))

    def request_previews(self, record_ids: list[str]) -> list[dict[str, object]]:
        """Return portable review data for a shared JSON approval request."""
        selected = {str(value) for value in record_ids if str(value).strip()}
        if not selected:
            return []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected)).order_by(IngestionRecordModel.row_number)).all()
            previews = []
            for row in rows:
                payload = json.loads(row.normalized_json)
                previews.append({
                    "record_id": row.record_id,
                    "source_record_key": row.source_record_key,
                    "source_system": row.source_system,
                    "source_file": self._source_file_name(row.source_file),
                    "status": row.status,
                    "match_status": row.match_status,
                    "match_reason": row.match_reason,
                    "worker_name": " ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part),
                    "email": payload.get("email", ""),
                    "vendor": payload.get("vendor_name", "") or payload.get("statement_of_work", "").split(maxsplit=1)[0],
                    "identifier": payload.get("accessnow_employee_id", "") or payload.get("accessnow_nuid", "") or payload.get("vendor_employee_id", "") or payload.get("supplier_reference", "") or payload.get("worker_id", ""),
                    "statement_of_work": payload.get("statement_of_work", ""),
                })
            return previews

    def resolve_import_record_ids(self, payload: dict[str, object]) -> list[str]:
        """Resolve shared request records on this workstation.

        UUIDs are local implementation identifiers and can differ when the
        same source workbook is ingested on another workstation. Prefer the
        UUID, then resolve portable previews by source system and source row
        key so a shared approval can be applied locally.
        """
        requested = {str(value) for value in payload.get("record_ids", []) if str(value).strip()}
        previews = payload.get("record_previews", [])
        portable_keys = {
            (str(item.get("source_system", "")), str(item.get("source_record_key", "")))
            for item in previews if isinstance(item, dict) and item.get("source_system") and item.get("source_record_key")
        }
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(requested))).all() if requested else []
            resolved = {row.record_id for row in rows}
            if portable_keys:
                candidates = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.source_system.in_({key[0] for key in portable_keys}))).all()
                resolved.update(row.record_id for row in candidates if (row.source_system, row.source_record_key) in portable_keys)
        return sorted(resolved)

    def apply_approved_import_records(self, record_ids: list[str], actor: str, *, request_payload: dict[str, object] | None = None) -> dict[str, object]:
        """Apply approved source records through their source-specific adapter."""
        from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter, SOURCE_SYSTEM
        from .accessnow_ingestion_service import AccessNowIngestionService, SOURCE_SYSTEM as ACCESSNOW_SOURCE

        if request_payload is not None:
            record_ids = self.resolve_import_record_ids(request_payload)
        with orm_session(self.database_path) as session:
            source_systems = set(session.scalars(select(IngestionRecordModel.source_system).where(IngestionRecordModel.record_id.in_(record_ids))).all())
        result: dict[str, object] = {"processed": 0, "created": 0, "reused": 0, "failed": 0, "errors": []}
        roster_ids = []
        rsr_ids = []
        accessnow_ids = []
        for record_id in record_ids:
            with orm_session(self.database_path) as session:
                record = session.get(IngestionRecordModel, record_id)
                if record is None:
                    continue
                if record.source_system == SOURCE_SYSTEM:
                    rsr_ids.append(record_id)
                elif record.source_system == ACCESSNOW_SOURCE:
                    accessnow_ids.append(record_id)
                else:
                    roster_ids.append(record_id)
        if rsr_ids:
            rsr_result = RsrSupplierWorkerDetailsAdapter(self.database_path).apply_approved_records(rsr_ids, actor)
            self._sync_applied_source_profiles(rsr_ids)
            result["processed"] = int(result["processed"]) + int(rsr_result["processed"])
            result["created"] = int(result["created"]) + int(rsr_result.get("created", 0))
            result["reused"] = int(result["reused"]) + int(rsr_result.get("reused", 0))
            result["failed"] = int(result["failed"]) + int(rsr_result["failed"])
            result["errors"] = list(result["errors"]) + list(rsr_result["errors"])
        if accessnow_ids:
            accessnow_result = AccessNowIngestionService(self.database_path).apply_approved_records(accessnow_ids, actor)
            self._sync_applied_source_profiles(accessnow_ids)
            result["processed"] = int(result["processed"]) + int(accessnow_result["processed"])
            result["created"] = int(result["created"]) + int(accessnow_result.get("created", 0))
            result["reused"] = int(result["reused"]) + int(accessnow_result.get("reused", 0))
            result["failed"] = int(result["failed"]) + int(accessnow_result["failed"])
            result["errors"] = list(result["errors"]) + list(accessnow_result["errors"])
        if roster_ids:
            roster_result = self.promote_staged_records(roster_ids, actor)
            result["processed"] = int(result["processed"]) + int(roster_result["processed"])
            result["created"] = int(result["created"]) + int(roster_result["created"])
            result["reused"] = int(result["reused"]) + int(roster_result["reused"])
            result["failed"] = int(result["failed"]) + int(roster_result["failed"])
            result["errors"] = list(result["errors"]) + list(roster_result["errors"])
        return result

    def _sync_applied_source_profiles(self, record_ids: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.record_id.in_(set(record_ids)),
                IngestionRecordModel.matched_worker_id.is_not(None),
                IngestionRecordModel.status.in_(("APPLIED", "LINKED", "CURRENT", "MATCHED")),
            )).all()
            for record in records:
                self._supersede_previous_source_record_in_session(session, record, now)
                record.observation_state = "CURRENT"
                record.linked_at_utc = record.linked_at_utc or now
                record.last_seen_at_utc = now
                self._upsert_source_profile(session, record, str(record.matched_worker_id), now)
            session.commit()

    def apply_selected_source_updates(self, worker_id: str, record_ids: list[str], fields: list[str], actor: str) -> dict[str, object]:
        """Apply selected incoming fields locally and append immutable history."""
        selected = {str(value).strip() for value in fields if str(value).strip()}
        record_set = {str(value).strip() for value in record_ids if str(value).strip()}
        if not record_set:
            raise ValueError("No source records were selected.")
        if not selected:
            raise ValueError("Select at least one field to apply.")
        source_fields = {
            "first_name": ("worker", "first_name"), "last_name": ("worker", "last_name"),
            "email": ("worker", "canonical_email"), "vendor_email": ("worker", "canonical_email"), "vendor_email_address": ("worker", "canonical_email"),
            "vendor_name": ("engagement", "vendor_name"), "job_title": ("engagement", "job_title"),
            "lob": ("engagement", "lob"), "program": ("engagement", "program"), "project": ("engagement", "project"),
            "country": ("engagement", "country"), "site_location": ("engagement", "site_location"),
            "supervisor_name": ("engagement", "supervisor_name"), "worker_start_date": ("engagement", "onboarding_date"),
            "accessnow_status": ("worker", "status"),
            "worker_end_date": ("engagement", "production_start_date"), "worker_status": ("engagement", "status"),
            "npn": ("engagement", "npn"), "resident_license_state": ("engagement", "license_state"),
            "resident_license_number": ("engagement", "license_number"), "taxonomy": ("engagement", "taxonomy_code"),
            "key_billable_function": ("engagement", "key_billable_function"),
        }
        applied, changed_fields = 0, set()
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                raise ValueError("Worker was not found.")
            engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(record_set), IngestionRecordModel.matched_worker_id == worker_id)).all()
            if not records:
                raise ValueError("The selected source records no longer match this employee.")
            for record in records:
                if record.status not in {"STAGED", "MATCHED", "CONFLICT"}:
                    continue
                payload = json.loads(record.normalized_json)
                if record.source_system == "ACCESSNOW":
                    record_engagement = None
                elif record.source_system in {"ROSTER_LOCK", "RSR_SUPPLIER_WORKER_DETAILS"}:
                    record_engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id, WorkerEngagementModel.source_system == record.source_system).order_by(WorkerEngagementModel.updated_at_utc.desc()))
                else:
                    record_engagement = engagement
                for source_field in selected:
                    target = source_fields.get(source_field)
                    incoming = str(payload.get(source_field) or "").strip()
                    if not target or not incoming:
                        continue
                    owner, attribute = target
                    if owner == "worker":
                        current = str(getattr(worker, attribute) or "")
                        if attribute != "status" and current:
                            continue
                        setattr(worker, attribute, incoming.lower() if attribute == "canonical_email" else incoming)
                        if attribute in {"first_name", "last_name"}:
                            worker.display_name = " ".join(part for part in (worker.first_name, worker.last_name) if part)
                    else:
                        if record_engagement is None:
                            record_engagement = WorkerEngagementModel(engagement_id=str(uuid.uuid4()), worker_id=worker_id, source_system=record.source_system, created_at_utc=now, updated_at_utc=now)
                            session.add(record_engagement)
                        current = str(getattr(record_engagement, attribute) or "")
                        if current:
                            continue
                        setattr(record_engagement, attribute, incoming)
                        record_engagement.updated_at_utc = now
                    if current.casefold() != incoming.casefold():
                        changed_fields.add(attribute)
                for field_name, value in payload.items():
                    session.add(WorkerSourceLineageModel(lineage_id=str(uuid.uuid4()), worker_id=worker_id, engagement_id=record_engagement.engagement_id if record_engagement else None, batch_id=record.batch_id, source_system=record.source_system, source_file=record.source_file, source_checksum=record.source_checksum, row_number=record.row_number, field_name=field_name, raw_value=str(value or ""), normalized_value=str(value or ""), observed_at_utc=now))
                record.status = "APPLIED"
                applied += 1
            if changed_fields:
                record_worker_version(session, worker_id, actor=actor, change_type="SELECTIVE_SOURCE_UPDATE", source_system="LOCAL_REVIEW", changed_fields=sorted(changed_fields))
            session.commit()
        mark_publication_pending(self.database_path, actor=actor, reason="Selective source update applied locally")
        return {"processed": applied, "applied": applied, "changed_fields": sorted(changed_fields), "actor": actor}

    def apply_change_request(self, request_id: str, operation_type: str, worker_id: str, payload: dict[str, object], actor: str) -> dict[str, object]:
        """Apply an approved employee request to this runtime and record its history."""
        now = datetime.now(timezone.utc).isoformat()
        worker_fields = {"first_name": "first_name", "last_name": "last_name", "email": "canonical_email", "status": "status"}
        engagement_fields = {"job_title": "job_title", "lob": "lob", "vendor_name": "vendor_name", "program": "program", "project": "project", "country": "country", "site_location": "site_location", "supervisor_name": "supervisor_name", "onboarding_date": "onboarding_date", "production_start_date": "production_start_date", "engagement_status": "status", "npn": "npn", "license_state": "license_state", "license_number": "license_number", "taxonomy_code": "taxonomy_code", "key_billable_function": "key_billable_function"}
        changed_fields: list[str] = []
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if operation_type == "CREATE_EMPLOYEE":
                if worker is not None:
                    raise ValueError("The requested employee already exists.")
                worker = WorkerModel(worker_id=worker_id, first_name=str(payload.get("first_name") or ""), last_name=str(payload.get("last_name") or ""), display_name=" ".join(str(payload.get(key) or "").strip() for key in ("first_name", "last_name") if str(payload.get(key) or "").strip()), canonical_email=str(payload.get("email") or "").strip().lower(), status=str(payload.get("status") or "ACTIVE"), record_version=0, created_at_utc=now, updated_at_utc=now)
                session.add(worker)
                changed_fields = sorted(payload.keys())
            else:
                if worker is None:
                    raise ValueError("The requested employee was not found in the local runtime.")
                engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
                for field, attribute in worker_fields.items():
                    if field not in payload:
                        continue
                    value = str(payload[field] or "").strip()
                    setattr(worker, attribute, value.lower() if attribute == "canonical_email" else value)
                    changed_fields.append(attribute)
                for field, attribute in engagement_fields.items():
                    if field not in payload:
                        continue
                    if engagement is None:
                        engagement = WorkerEngagementModel(engagement_id=str(uuid.uuid4()), worker_id=worker_id, source_system="CHANGE_REQUEST", created_at_utc=now, updated_at_utc=now)
                        session.add(engagement)
                    setattr(engagement, attribute, str(payload[field] or "").strip())
                    engagement.updated_at_utc = now
                    changed_fields.append(attribute)
                if "first_name" in payload or "last_name" in payload:
                    worker.display_name = " ".join(part for part in (worker.first_name, worker.last_name) if part)
                if "identifier_updates" in payload:
                    for identifier_id, value in dict(payload["identifier_updates"]).items():
                        identifier = session.get(WorkerIdentifierModel, identifier_id)
                        if identifier:
                            identifier.identifier_value = str(value)
                            identifier.normalized_value = str(value).casefold()
                            changed_fields.append("identifiers")
                if "lineage_updates" in payload:
                    for lineage_id, value in dict(payload["lineage_updates"]).items():
                        lineage_item = session.get(WorkerSourceLineageModel, lineage_id)
                        if lineage_item and lineage_item.worker_id == worker_id:
                            new_value = str(value or "").strip()
                            if lineage_item.normalized_value != new_value:
                                lineage_item.raw_value = new_value
                                lineage_item.normalized_value = new_value
                                lineage_item.observed_at_utc = now
                                changed_fields.append(f"lineage:{lineage_item.field_name}")
                if operation_type == "DEACTIVATE_EMPLOYEE" and "status" not in payload:
                    worker.status = "INACTIVE"
                    changed_fields.append("status")
            record_worker_version(session, worker_id, actor=actor, change_type="CHANGE_REQUEST_APPLIED", source_system="CHANGE_REQUEST", source_record_key=request_id, changed_fields=sorted(set(changed_fields)))
            session.commit()
        mark_publication_pending(self.database_path, actor=actor, reason=f"Approved change request {request_id} applied locally")
        return {"request_id": request_id, "worker_id": worker_id, "changed_fields": sorted(set(changed_fields)), "applied": True, "actor": actor}

    def change_request_has_history(self, request_id: str) -> bool:
        with orm_session(self.database_path) as session:
            # Versions created by the earlier bug were empty baselines. They
            # must be eligible for one reconciliation pass so their payload
            # can be applied and recorded correctly.
            return bool(session.scalar(select(WorkerProfileVersionModel.version_id).where(WorkerProfileVersionModel.source_record_key == request_id, WorkerProfileVersionModel.changed_fields_json != "[]").limit(1)))

    def refresh_rsr_matches(self) -> dict[str, int]:
        """Refresh enrichment-source matching after canonical workers change."""
        from ..source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter

        return RsrSupplierWorkerDetailsAdapter(self.database_path).refresh_matches()

    def get_worker(self, worker_id: str) -> dict[str, object] | None:
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return None
            identifiers = session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker_id).order_by(WorkerIdentifierModel.source_system, WorkerIdentifierModel.identifier_type)).all()
            engagements = session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.created_at_utc.desc())).all()
            lineage = session.scalars(select(WorkerSourceLineageModel).where(WorkerSourceLineageModel.worker_id == worker_id).order_by(WorkerSourceLineageModel.observed_at_utc.desc())).all()
            source_rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.matched_worker_id == worker_id).order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number.desc())).all()
            source_observations = []
            for row in source_rows:
                try:
                    payload = json.loads(row.normalized_json or "{}")
                except json.JSONDecodeError:
                    payload = {}
                source_observations.append({
                    "record_id": row.record_id,
                    "source_system": row.source_system,
                    "source_file": self._source_file_name(row.source_file),
                    "source_checksum": row.source_checksum,
                    "source_record_key": row.source_record_key,
                    "row_number": row.row_number,
                    "status": row.status,
                    "observation_state": row.observation_state,
                    "created_at_utc": row.created_at_utc,
                    "payload": payload,
                })
            discrepancies = session.scalars(select(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id == worker_id).order_by(WorkerDiscrepancyModel.created_at_utc.desc())).all()
            versions = session.scalars(select(WorkerProfileVersionModel).where(WorkerProfileVersionModel.worker_id == worker_id).order_by(WorkerProfileVersionModel.version_number.desc())).all()
            version_items = [version_dict(item) for item in versions]
            for index, item in enumerate(version_items):
                previous = version_items[index + 1]["snapshot"] if index + 1 < len(version_items) else {}
                previous_engagement = (previous.get("engagements") or [{}])[0]
                current_engagement = (item["snapshot"].get("engagements") or [{}])[0]
                item["changes"] = []
                for field in item["changed_fields"]:
                    if field.startswith("lineage:"):
                        lineage_field = field.split(":", 1)[1]
                        current_value = next((row.get("normalized_value", "") for row in item["snapshot"].get("lineage", []) if row.get("field_name") == lineage_field), "")
                        previous_value = next((row.get("normalized_value", "") for row in previous.get("lineage", []) if row.get("field_name") == lineage_field), "")
                    else:
                        current_value = item["snapshot"].get(field, current_engagement.get(field, ""))
                        previous_value = previous.get(field, previous_engagement.get(field, ""))
                    item["changes"].append({"field": field, "previous_value": previous_value or "Not set", "new_value": current_value or "Not set"})
            source_names = sorted({item.source_system for item in identifiers if item.source_system} | {item.source_system for item in engagements if item.source_system} | {item.source_system for item in lineage if item.source_system})
            source_profiles = []
            for source_system in source_names:
                source_profiles.append({
                    "source_system": source_system,
                    "identifiers": [item for item in identifiers if item.source_system == source_system],
                    "engagements": [item for item in engagements if item.source_system == source_system],
                    "lineage": [item for item in lineage if item.source_system == source_system],
                })
            return {"worker": worker, "identifiers": identifiers, "engagements": engagements, "lineage": lineage, "source_profiles": source_profiles, "source_observations": source_observations, "discrepancies": discrepancies, "versions": version_items}

    def source_update_preview(self, worker_id: str, source_file: str = "") -> dict[str, object] | None:
        """Return only pending source rows that affect one canonical worker.

        Source workbooks remain immutable evidence. This preview compares staged
        rows against the canonical worker and current engagement without
        promoting or mutating either record.
        """
        source_fields = {
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "canonical_email",
            "vendor_email": "canonical_email",
            "vendor_name": "vendor_name",
            "job_title": "job_title",
            "lob": "lob",
            "program": "program",
            "project": "project",
            "country": "country",
            "site_location": "site_location",
            "supervisor_name": "supervisor_name",
            "worker_start_date": "onboarding_date",
            "worker_end_date": "production_start_date",
            "worker_status": "engagement_status",
            "accessnow_status": "status",
            "npn": "npn",
            "resident_license_state": "license_state",
            "resident_license_number": "license_number",
            "taxonomy": "taxonomy_code",
            "key_billable_function": "key_billable_function",
            "vendor_employee_id": "identifier_vendor_employee_id",
            "supplier_reference": "identifier_supplier_reference",
            "fieldglass_id": "identifier_fieldglass_id",
            "nuid": "identifier_nuid",
            "salesforce_id": "identifier_salesforce_id",
        }
        with orm_session(self.database_path) as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return None
            engagement = session.scalar(
                select(WorkerEngagementModel)
                .where(WorkerEngagementModel.worker_id == worker_id)
                .order_by(WorkerEngagementModel.updated_at_utc.desc())
            )
            identifiers = session.scalars(
                select(WorkerIdentifierModel)
                .where(WorkerIdentifierModel.worker_id == worker_id)
                .order_by(WorkerIdentifierModel.identifier_type)
            ).all()
            current = {
                "first_name": worker.first_name or "",
                "last_name": worker.last_name or "",
                "canonical_email": worker.canonical_email or "",
                "status": worker.status or "",
                **{
                    f"identifier_{item.identifier_type.lower()}": item.identifier_value or ""
                    for item in identifiers
                },
                **({
                    "vendor_name": engagement.vendor_name or "",
                    "job_title": engagement.job_title or "",
                    "lob": engagement.lob or "",
                    "program": engagement.program or "",
                    "project": engagement.project or "",
                    "country": engagement.country or "",
                    "site_location": engagement.site_location or "",
                    "supervisor_name": engagement.supervisor_name or "",
                    "onboarding_date": engagement.onboarding_date or "",
                    "production_start_date": engagement.production_start_date or "",
                    "engagement_status": engagement.status or "",
                    "npn": engagement.npn or "",
                    "license_state": engagement.license_state or "",
                    "license_number": engagement.license_number or "",
                    "taxonomy_code": engagement.taxonomy_code or "",
                    "key_billable_function": engagement.key_billable_function or "",
                } if engagement else {}),
            }
            rows = session.scalars(
                select(IngestionRecordModel)
                .where(
                    IngestionRecordModel.matched_worker_id == worker_id,
                    IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT")),
                )
                .order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number.desc())
            ).all()
            selected_file = self._source_file_name(source_file) if source_file else ""
            if selected_file:
                rows = [row for row in rows if self._source_file_name(row.source_file) == selected_file]
            updates: list[dict[str, object]] = []
            seen: set[tuple[str, str, str]] = set()
            incoming_by_field: dict[str, dict[str, str]] = {}
            for row in rows:
                payload = json.loads(row.normalized_json)
                changes: list[dict[str, str]] = []
                for source_field, canonical_field in source_fields.items():
                    incoming = str(payload.get(source_field) or "").strip()
                    if not incoming:
                        continue
                    current_value = str(current.get(canonical_field) or "").strip()
                    incoming_by_field.setdefault(canonical_field, {
                        "incoming_value": incoming,
                        "source_field": source_field,
                        "source_system": row.source_system,
                        "source_file": self._source_file_name(row.source_file),
                        "record_id": row.record_id,
                    })
                    if incoming.casefold() == current_value.casefold():
                        continue
                    key = (canonical_field, current_value.casefold(), incoming.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    changes.append({
                        "field": canonical_field,
                        "source_field": source_field,
                        "current_value": current_value,
                        "incoming_value": incoming,
                    })
                if changes:
                    updates.append({
                        "record_id": row.record_id,
                        "source_system": row.source_system,
                        "source_file": self._source_file_name(row.source_file),
                        "source_record_key": row.source_record_key,
                        "source_checksum": row.source_checksum,
                        "row_number": row.row_number,
                        "match_status": row.match_status,
                        "changes": changes,
                    })
            fields: list[dict[str, object]] = []
            for field_name, current_value in current.items():
                incoming = incoming_by_field.get(field_name, {})
                incoming_value = str(incoming.get("incoming_value", ""))
                changed = bool(incoming_value) and incoming_value.casefold() != str(current_value).casefold()
                fields.append({
                    "field": field_name,
                    "current_value": str(current_value),
                    "incoming_value": incoming_value,
                    "changed": changed,
                    "source_field": incoming.get("source_field", ""),
                    "source_system": incoming.get("source_system", ""),
                    "source_file": incoming.get("source_file", ""),
                    "record_id": incoming.get("record_id", ""),
                })
            return {
                "worker_id": worker_id,
                "worker_name": worker.display_name,
                "updates": updates,
                "fields": fields,
                "new_employee_records": [],
            }

    def new_employee_source_preview(self, source_file: str = "") -> list[dict[str, object]]:
        """Return staged source rows that have no canonical worker match."""
        with orm_session(self.database_path) as session:
            rows = session.scalars(
                select(IngestionRecordModel)
                .where(
                    IngestionRecordModel.status.in_(("STAGED", "MATCHED", "UNMATCHED", "AMBIGUOUS", "CONFLICT")),
                    IngestionRecordModel.match_status.in_(("UNMATCHED", "AMBIGUOUS", "NOT_EVALUATED")),
                )
                .order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)
            ).all()
            selected_file = self._source_file_name(source_file) if source_file else ""
            if selected_file:
                rows = [row for row in rows if self._source_file_name(row.source_file) == selected_file]
            result = []
            for row in rows:
                payload = json.loads(row.normalized_json)
                result.append({
                    "record_id": row.record_id,
                    "source_system": row.source_system,
                    "source_file": self._source_file_name(row.source_file),
                    "source_record_key": row.source_record_key,
                    "match_status": row.match_status,
                    "match_reason": row.match_reason,
                    "worker_name": " ".join(part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part),
                    "email": payload.get("email", ""),
                    "identifier": payload.get("accessnow_employee_id", "") or payload.get("accessnow_nuid", "") or payload.get("vendor_employee_id", "") or payload.get("supplier_reference", "") or payload.get("worker_id", ""),
                    "payload": payload,
                    "batch_id": row.batch_id,
                    "source_checksum": row.source_checksum,
                })
            return result

    def source_candidate_preview(self, record_id: str) -> dict[str, object] | None:
        """Return one candidate together with every matching source observation."""
        with orm_session(self.database_path) as session:
            row = session.get(IngestionRecordModel, record_id)
            if row is None:
                return None
            base_payload = json.loads(row.normalized_json or "{}")
            base_keys = self._candidate_keys(base_payload, row.source_record_key)
            all_rows = session.scalars(select(IngestionRecordModel).order_by(IngestionRecordModel.created_at_utc, IngestionRecordModel.row_number)).all()
            evidence = []
            for candidate in all_rows:
                payload = json.loads(candidate.normalized_json or "{}")
                if not base_keys.intersection(self._candidate_keys(payload, candidate.source_record_key)):
                    continue
                evidence.append({
                    "record_id": candidate.record_id,
                    "source_system": candidate.source_system,
                    "source_file": self._source_file_name(candidate.source_file),
                    "row_number": candidate.row_number,
                    "source_record_key": candidate.source_record_key,
                    "source_checksum": candidate.source_checksum,
                    "status": candidate.status,
                    "match_status": candidate.match_status,
                    "match_reason": candidate.match_reason,
                    "observation_state": candidate.observation_state or "PENDING",
                    "matched_worker_id": candidate.matched_worker_id or "",
                    "created_at_utc": candidate.created_at_utc,
                    "payload": payload,
                })
            evidence.sort(key=lambda item: (item["source_system"], item["source_file"], item["row_number"]))
            worker_ids = sorted({item["matched_worker_id"] for item in evidence if item["matched_worker_id"]})
            return {
                "record_id": row.record_id,
                "batch_id": row.batch_id,
                "source_system": row.source_system,
                "source_file": self._source_file_name(row.source_file),
                "source_record_key": row.source_record_key,
                "source_checksum": row.source_checksum,
                "status": row.status,
                "match_status": row.match_status,
                "match_reason": row.match_reason,
                "worker_name": " ".join(part for part in (base_payload.get("first_name") or base_payload.get("employee_first_name", ""), base_payload.get("last_name") or base_payload.get("employee_last_name", "")) if part),
                "payload": base_payload,
                "records": evidence,
                "source_count": len({item["source_system"] for item in evidence}),
                "file_count": len({(item["source_system"], item["source_file"]) for item in evidence}),
                "worker_ids": worker_ids,
            }

    @staticmethod
    def _candidate_keys(payload: dict[str, object], source_record_key: str = "") -> set[str]:
        """Build conservative cross-source keys for one candidate dossier."""
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

    def search_source_people(self, query: str) -> list[dict[str, object]]:
        """Search all imported source rows and group them into candidate dossiers."""
        needle = query.strip().casefold()
        if not needle:
            return []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)).all()
            matches = []
            for row in rows:
                payload = json.loads(row.normalized_json or "{}")
                searchable = " ".join([row.source_record_key, row.source_file, *[str(value or "") for value in payload.values()]]).casefold()
                if needle not in searchable:
                    continue
                name = " ".join(part for part in (payload.get("first_name") or payload.get("employee_first_name", ""), payload.get("last_name") or payload.get("employee_last_name", "")) if part)
                matches.append({"record_id": row.record_id, "worker_name": name, "source_system": row.source_system, "source_file": self._source_file_name(row.source_file), "source_record_key": row.source_record_key, "matched_worker_id": row.matched_worker_id or ""})
            groups: dict[tuple[str, str], list[dict[str, object]]] = {}
            for item in matches:
                identity = str(item["worker_name"]).casefold() or str(item["source_record_key"]).casefold()
                key = (identity, "")
                groups.setdefault(key, []).append(item)
            result = []
            for items in groups.values():
                first = items[0]
                result.append({"record_id": first["record_id"], "worker_name": first["worker_name"] or "Unnamed candidate", "record_count": len(items), "source_count": len({item["source_system"] for item in items}), "file_count": len({(item["source_system"], item["source_file"]) for item in items}), "matched_worker_id": first["matched_worker_id"], "sources": sorted({str(item["source_system"]) for item in items}), "records": items})
            return sorted(result, key=lambda item: (str(item["worker_name"]).casefold(), -int(item["record_count"])))

    def list_source_people(self) -> list[dict[str, object]]:
        """List all non-superseded source people as lightweight dossiers."""
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.status.in_(("STAGED", "MATCHED", "UNMATCHED", "AMBIGUOUS", "CONFLICT")),
                IngestionRecordModel.observation_state != "SUPERSEDED",
            ).order_by(IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)).all()
            groups: dict[str, list[dict[str, object]]] = {}
            for row in rows:
                payload = json.loads(row.normalized_json or "{}")
                name = " ".join(part for part in (payload.get("first_name") or payload.get("employee_first_name", ""), payload.get("last_name") or payload.get("employee_last_name", "")) if part)
                keys = self._candidate_keys(payload, row.source_record_key)
                identity = next((key for key in sorted(keys) if key.startswith("name:")), None) or next((key for key in sorted(keys) if key.startswith("email:")), None) or next(iter(sorted(keys)), f"record:{row.record_id}")
                groups.setdefault(identity, []).append({"record_id": row.record_id, "worker_name": name, "source_system": row.source_system, "source_file": self._source_file_name(row.source_file), "source_record_key": row.source_record_key, "matched_worker_id": row.matched_worker_id or ""})
            result = []
            for items in groups.values():
                first = items[0]
                result.append({"record_id": first["record_id"], "worker_name": first["worker_name"] or "Unnamed candidate", "record_count": len(items), "source_count": len({item["source_system"] for item in items}), "file_count": len({(item["source_system"], item["source_file"]) for item in items}), "matched_worker_id": first["matched_worker_id"], "sources": sorted({str(item["source_system"]) for item in items}), "records": items})
            return sorted(result, key=lambda item: str(item["worker_name"]).casefold())

    def prepare_source_candidate(self, record_ids: list[str], actor: str) -> dict[str, object]:
        """Create/reuse one canonical worker before applying a multi-source dossier."""
        selected = {str(value).strip() for value in record_ids if str(value).strip()}
        if not selected:
            raise ValueError("The candidate dossier contains no source records.")
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected))).all()
            if not records:
                raise ValueError("The candidate source records were not found.")
            worker_ids = {str(record.matched_worker_id) for record in records if record.matched_worker_id}
            if len(worker_ids) > 1:
                raise ValueError("The candidate dossier is linked to more than one canonical employee.")
            worker_id = next(iter(worker_ids), "")
            created = False
            worker = session.get(WorkerModel, worker_id) if worker_id else None
            if worker is None:
                payloads = [json.loads(record.normalized_json or "{}") for record in records]
                payloads.sort(key=lambda payload: (bool(payload.get("email") or payload.get("vendor_email") or payload.get("vendor_email_address")), bool(payload.get("first_name") or payload.get("employee_first_name")), len(payload)), reverse=True)
                payload = payloads[0]
                first_name = str(payload.get("first_name") or payload.get("employee_first_name") or "").strip()
                last_name = str(payload.get("last_name") or payload.get("employee_last_name") or "").strip()
                worker_id = str(uuid.uuid4())
                worker = WorkerModel(
                    worker_id=worker_id, first_name=first_name, last_name=last_name,
                    display_name=" ".join(part for part in (first_name, last_name) if part),
                    canonical_email=str(payload.get("email") or payload.get("vendor_email") or payload.get("vendor_email_address") or "").strip().lower(),
                    status="ACTIVE", record_version=1, created_at_utc=now, updated_at_utc=now,
                )
                session.add(worker)
                created = True
            for record in records:
                record.matched_worker_id = worker_id
                record.match_status = "MATCHED"
                record.match_reason = "Candidate dossier consolidated into one canonical employee"
            session.commit()
        return {"worker_id": worker_id, "created": created, "record_ids": sorted(selected), "actor": actor}

    def create_all_source_candidates(self, actor: str) -> dict[str, object]:
        """Create one canonical employee per eligible pending dossier."""
        people = self.list_source_people()
        result = {"dossiers": 0, "created": 0, "reused": 0, "processed": 0, "skipped": 0, "failed": 0, "errors": []}
        for person in people:
            record_ids = [str(item["record_id"]) for item in person.get("records", [])]
            try:
                with orm_session(self.database_path) as session:
                    rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(record_ids))).all()
                    if not rows or any(row.match_status in {"AMBIGUOUS", "CONFLICT"} for row in rows):
                        result["skipped"] += 1
                        continue
                preparation = self.prepare_source_candidate(record_ids, actor)
                applied = self.apply_approved_import_records(record_ids, actor)
                result["dossiers"] += 1
                result["created"] += int(bool(preparation["created"]))
                result["reused"] += int(not preparation["created"])
                result["processed"] += int(applied.get("processed", 0))
                result["failed"] += int(applied.get("failed", 0))
                result["errors"].extend(applied.get("errors", []))
            except (OSError, ValueError, PermissionError, json.JSONDecodeError) as exc:
                result["failed"] += 1
                result["errors"].append({"record_id": record_ids[0] if record_ids else "", "error": str(exc)})
        return result

    def source_update_overview(self, source_file: str = "") -> dict[str, object]:
        """Build the compact review worklist for the Employees area."""
        selected_file = self._source_file_name(source_file) if source_file else ""
        pending_records = self._pending_source_records(selected_file)
        worker_ids = sorted({str(record.matched_worker_id) for record in pending_records if record.matched_worker_id})
        existing = []
        for worker_id in worker_ids:
            preview = self.source_update_preview(str(worker_id), source_file=selected_file)
            if preview and preview["updates"]:
                existing.append(preview)
        new_records = self.new_employee_source_preview(source_file=selected_file)
        return {
            "existing_updates": existing,
            "new_employee_records": new_records,
            "duplicate_summary": self.source_duplicate_summary(source_file=selected_file),
            "source_files": sorted({self._source_file_name(record.source_file) for record in self._pending_source_records() if record.source_file}),
            "selected_source_file": selected_file,
            "pending_count": len(new_records) + sum(len(item.get("updates", [])) for item in existing),
        }

    def source_duplicate_summary(self, source_file: str = "") -> dict[str, object]:
        """Group pending source records that may describe the same person.

        This is intentionally a review signal, not an automatic merge. Strong
        identifiers are preferred; name and email are used only as a weaker
        fallback when no identifier is available. A group whose records already
        resolve to one canonical worker is corroborating source history rather
        than a duplicate canonical employee.
        """
        signal_definitions = (
            ("AccessNow Employee ID", "accessnow_employee_id"),
            ("AccessNow NUID", "accessnow_nuid"),
            ("Vendor employee ID", "vendor_employee_id"),
            ("Supplier reference", "supplier_reference"),
            ("Worker ID", "worker_id"),
            ("Fieldglass ID", "fieldglass_id"),
            ("NUID", "nuid"),
        )
        groups: dict[tuple[str, str, str], dict[str, object]] = {}
        records = self._pending_source_records(source_file)

        for record in records:
            try:
                payload = json.loads(record.normalized_json or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue

            signals: list[tuple[str, str]] = []
            for label, field_name in signal_definitions:
                value = str(payload.get(field_name) or "").strip()
                if value:
                    signals.append((label, value.casefold()))
            if not signals:
                first_name = str(payload.get("first_name") or payload.get("employee_first_name") or "").strip()
                last_name = str(payload.get("last_name") or payload.get("employee_last_name") or "").strip()
                email = str(payload.get("email") or payload.get("vendor_email_address") or "").strip()
                if first_name and last_name and email:
                    signals.append(("Name + email", f"{first_name} {last_name}|{email}".casefold()))
            if not signals:
                continue

            item = {
                "record_id": record.record_id,
                "source_system": record.source_system,
                "source_file": self._source_file_name(record.source_file),
                "source_record_key": record.source_record_key,
                "matched_worker_id": record.matched_worker_id,
                "created_at_utc": record.created_at_utc,
                "worker_name": " ".join(
                    part for part in (
                        payload.get("first_name") or payload.get("employee_first_name") or "",
                        payload.get("last_name") or payload.get("employee_last_name") or "",
                    ) if str(part).strip()
                ),
                "payload": payload,
            }
            for label, normalized_value in signals:
                group_key = (record.source_system, label, normalized_value)
                group = groups.setdefault(
                    group_key,
                    {
                        "source_system": record.source_system,
                        "signal": label,
                        "value": str(dict(signals).get(label, normalized_value)),
                        "records": [],
                    },
                )
                group["records"].append(item)

        duplicate_groups = []
        seen_group_records: set[tuple[str, str]] = set()
        for group in groups.values():
            records_in_group = group["records"]
            unique_records = {item["record_id"] for item in records_in_group}
            if len(unique_records) < 2:
                continue
            worker_ids = {item["matched_worker_id"] for item in records_in_group if item["matched_worker_id"]}
            classification = "CORROBORATED" if len(worker_ids) == 1 else "REVIEW_DUPLICATE"
            unique_items = []
            for item in records_in_group:
                marker = (group["value"], item["record_id"])
                if marker not in seen_group_records:
                    seen_group_records.add(marker)
                    unique_items.append(item)
            duplicate_groups.append(
                {
                    "source_system": group["source_system"],
                    "signal": group["signal"],
                    "value": group["value"],
                    "classification": classification,
                    "record_count": len(unique_items),
                    "records": unique_items,
                }
            )
        duplicate_groups.sort(key=lambda item: (-item["record_count"], item["signal"], item["value"]))
        return {
            "groups": duplicate_groups,
            "group_count": len(duplicate_groups),
            "record_count": len({item["record_id"] for group in duplicate_groups for item in group["records"]}),
        }

    def resolve_source_duplicate(self, record_id: str, actor: str) -> dict[str, object]:
        """Keep the newest row for one source key and archive older rows."""
        review = self.duplicate_review(record_id)
        if review is None:
            raise ValueError("The source repetition is no longer pending.")
        if not review["same_source"]:
            raise ValueError("Records from different source systems must remain separate.")
        records = list(review["records"])
        latest = max(records, key=lambda item: (str(item.get("created_at_utc") or ""), str(item.get("record_id") or "")))
        worker_ids = {str(item["matched_worker_id"]) for item in records if item.get("matched_worker_id")}
        if len(worker_ids) > 1:
            raise ValueError("The source key is linked to multiple canonical employees and needs manual resolution.")
        worker_id = next(iter(worker_ids), "")
        if worker_id:
            self.link_source_record(str(latest["record_id"]), worker_id, actor)
        elif str(latest["source_system"]) == "ROSTER_LOCK":
            now = datetime.now(timezone.utc).isoformat()
            with orm_session(self.database_path) as session:
                record = session.get(IngestionRecordModel, str(latest["record_id"]))
                if record is None:
                    raise ValueError("The newest source observation was not found.")
                worker_id, _ = self._promote_record_in_session(session, record, now, actor)
                session.commit()
        else:
            result = self.apply_approved_import_records([str(latest["record_id"])], actor)
            if int(result.get("failed", 0)):
                raise ValueError(str(result.get("errors") or "The newest source observation could not be applied."))
            with orm_session(self.database_path) as session:
                record = session.get(IngestionRecordModel, str(latest["record_id"]))
                worker_id = str(record.matched_worker_id or "") if record else ""
            if not worker_id:
                raise ValueError("The newest source observation did not create a canonical employee.")
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            source_records = session.scalars(select(IngestionRecordModel).where(
                IngestionRecordModel.record_id.in_([str(item["record_id"]) for item in records])
            )).all()
            for source_record in source_records:
                source_record.matched_worker_id = worker_id
                source_record.match_status = "MATCHED"
                source_record.linked_at_utc = source_record.linked_at_utc or now
                source_record.last_seen_at_utc = now
                if source_record.record_id == str(latest["record_id"]):
                    source_record.observation_state = "CURRENT"
                else:
                    source_record.observation_state = "SUPERSEDED"
                    source_record.status = "SUPERSEDED"
                    source_record.superseded_by_record_id = str(latest["record_id"])
                self._record_source_lineage_in_session(session, source_record, worker_id, now)
            session.commit()
        return {
            "worker_id": worker_id,
            "current_record_id": latest["record_id"],
            "superseded_record_ids": [item["record_id"] for item in records if item["record_id"] != latest["record_id"]],
            "source_system": latest["source_system"],
            "source_file": latest["source_file"],
            "actor": actor,
        }

    def duplicate_review(self, record_id: str) -> dict[str, object] | None:
        """Build one human-friendly, field-by-field duplicate comparison."""
        summary = self.source_duplicate_summary()
        group = next((item for item in summary["groups"] if any(row["record_id"] == record_id for row in item["records"])), None)
        if group is None:
            return None
        records = group["records"]
        worker_ids = {row["matched_worker_id"] for row in records if row.get("matched_worker_id")}
        worker_id = next(iter(worker_ids), "") if len(worker_ids) == 1 else ""
        current: dict[str, str] = {}
        if worker_id:
            detail = self.get_worker(worker_id)
            if detail:
                worker = detail["worker"]
                engagement = detail["engagements"][0] if detail["engagements"] else None
                current = {"first_name": worker.first_name or "", "last_name": worker.last_name or "", "email": worker.canonical_email or ""}
                if engagement:
                    for source_field, attribute in {
                        "vendor_name": "vendor_name", "job_title": "job_title", "lob": "lob", "program": "program", "project": "project", "country": "country", "site_location": "site_location", "supervisor_name": "supervisor_name", "worker_start_date": "onboarding_date", "worker_end_date": "production_start_date", "worker_status": "status", "npn": "npn", "resident_license_state": "license_state", "resident_license_number": "license_number", "taxonomy": "taxonomy_code", "key_billable_function": "key_billable_function",
                    }.items():
                        current[source_field] = str(getattr(engagement, attribute) or "")
        field_names = sorted({key for row in records for key, value in row.get("payload", {}).items() if str(value or "").strip()})
        fields = [{"name": name, "label": name.replace("_", " ").title(), "current_value": current.get(name, ""), "choices": [{"record_id": row["record_id"], "source": row["source_system"], "value": str(row["payload"].get(name) or "")} for row in records if str(row["payload"].get(name) or "").strip()]} for name in field_names]
        latest = max(records, key=lambda item: (str(item.get("created_at_utc") or ""), str(item.get("record_id") or "")))
        return {
            "group": group,
            "records": records,
            "worker_id": worker_id,
            "fields": fields,
            "same_source": len({row["source_system"] for row in records}) == 1,
            "latest_record_id": latest["record_id"],
            "latest_source_file": latest["source_file"],
            "latest_created_at": latest.get("created_at_utc", ""),
        }

    def _promote_record_in_session(self, session, record: IngestionRecordModel, now: str, actor: str = "system") -> tuple[str, bool]:
        """Promote one record while the caller owns the transaction."""
        payload = json.loads(record.normalized_json)
        identifier_value = str(payload.get("vendor_employee_id") or "").strip()
        if not identifier_value and not record.matched_worker_id:
            raise ValueError("The staged record has no Vendor Employee ID.")

        normalized_id = identifier_value.casefold()
        existing_identifier = session.scalar(select(WorkerIdentifierModel).where(
            WorkerIdentifierModel.source_system == "ROSTER_LOCK",
            WorkerIdentifierModel.identifier_type == "VENDOR_EMPLOYEE_ID",
            WorkerIdentifierModel.normalized_value == normalized_id,
        )) if normalized_id else None
        matched_worker = session.get(WorkerModel, str(record.matched_worker_id)) if record.matched_worker_id else None
        if matched_worker is not None:
            existing_identifier = existing_identifier or True
        created = existing_identifier is None
        if matched_worker is not None:
            worker_id = matched_worker.worker_id
            worker = matched_worker
        elif existing_identifier:
            worker_id = existing_identifier.worker_id
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                raise ValueError("The staged record references a missing canonical worker.")
        else:
            worker_id = str(uuid.uuid4())
            first_name = str(payload.get("first_name") or "").strip()
            last_name = str(payload.get("last_name") or "").strip()
            worker = WorkerModel(
                worker_id=worker_id,
                first_name=first_name,
                last_name=last_name,
                display_name=" ".join(part for part in (first_name, last_name) if part),
                canonical_email=str(payload.get("email") or "").strip().lower(),
                # A promoted canonical worker is active by default. Source or
                # engagement statuses remain preserved on the engagement.
                status="ACTIVE",
                record_version=1,
                created_at_utc=now,
                updated_at_utc=now,
            )
            session.add(worker)
        ensure_source_identifiers(session, worker_id, "ROSTER_LOCK", payload, now)

        engagement_id = str(uuid.uuid4())
        session.add(
            WorkerEngagementModel(
                engagement_id=engagement_id,
                worker_id=worker_id,
                vendor_name=str(payload.get("vendor_name") or ""),
                program=str(payload.get("program") or ""),
                project=str(payload.get("project") or ""),
                lob=str(payload.get("lob") or ""),
                supervisor_name=str(payload.get("supervisor_name") or ""),
                job_title=str(payload.get("job_title") or ""),
                country=str(payload.get("country") or ""),
                site_location=str(payload.get("site_location") or ""),
                onboarding_date=str(payload.get("onboarding_date") or ""),
                production_start_date=str(payload.get("production_start_date") or ""),
                status=str(payload.get("status") or "PENDING"),
                npn=str(payload.get("npn") or ""),
                license_state=str(payload.get("resident_license_state") or ""),
                license_number=str(payload.get("resident_license_number") or ""),
                taxonomy_code=str(payload.get("taxonomy_code") or ""),
                key_billable_function=str(payload.get("key_billable_function") or ""),
                statement_of_work=str(payload.get("statement_of_work") or ""),
                work_order_id=str(payload.get("work_order_id") or ""),
                primary_contact_name=str(payload.get("worker_primary_contact") or ""),
                source_system=record.source_system,
                created_at_utc=now,
                updated_at_utc=now,
            )
        )
        for field_name, value in payload.items():
            session.add(
                WorkerSourceLineageModel(
                    lineage_id=str(uuid.uuid4()),
                    worker_id=worker_id,
                    engagement_id=engagement_id,
                    batch_id=record.batch_id,
                    source_system=record.source_system,
                    source_file=record.source_file,
                    source_checksum=record.source_checksum,
                    row_number=record.row_number,
                    field_name=field_name,
                    raw_value=str(value or ""),
                    normalized_value=str(value or ""),
                    observed_at_utc=now,
                )
            )
        record.matched_worker_id = worker_id
        record.match_status = "MATCHED"
        record.status = "MATCHED"
        self._supersede_previous_source_record_in_session(session, record, now)
        record.observation_state = "CURRENT"
        record.linked_at_utc = now
        record.last_seen_at_utc = now
        self._upsert_source_profile(session, record, worker_id, now)
        record_worker_version(
            session,
            worker_id,
            actor=actor,
            change_type="ROSTER_LOCK_INITIAL_PROFILE" if created else "ROSTER_LOCK_ENRICHMENT",
            source_system=record.source_system,
            source_file=record.source_file,
            source_checksum=record.source_checksum,
            source_record_key=record.source_record_key,
            changed_fields=list(payload),
        )
        return worker_id, created

    def promote_all_staged_records(self, actor: str) -> dict[str, object]:
        """Promote all pending staged records in one transaction.

        A malformed row is reported in the result and does not prevent the
        valid rows from being promoted. The transaction is committed once at
        the end so the web application never performs one request per worker.
        """
        now = datetime.now(timezone.utc).isoformat()
        errors: list[dict[str, str]] = []
        processed = created = reused = 0
        with orm_session(self.database_path) as session:
            records = session.scalars(
                select(IngestionRecordModel)
                .where(IngestionRecordModel.status == "STAGED")
                .order_by(IngestionRecordModel.created_at_utc, IngestionRecordModel.row_number)
            ).all()
            for record in records:
                try:
                    _, was_created = self._promote_record_in_session(session, record, now, actor)
                    processed += 1
                    if was_created:
                        created += 1
                    else:
                        reused += 1
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "source_record_key": record.source_record_key, "error": str(exc)})
            session.commit()
        return {"processed": processed, "created": created, "reused": reused, "failed": len(errors), "errors": errors}

    def promote_staged_records(self, record_ids: list[str], actor: str) -> dict[str, object]:
        """Apply only the records approved by an import request."""
        selected_ids = {str(record_id) for record_id in record_ids if str(record_id).strip()}
        if not selected_ids:
            raise ValueError("The import request contains no staged records.")
        now = datetime.now(timezone.utc).isoformat()
        processed = created = reused = 0
        errors: list[dict[str, str]] = []
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected_ids))).all()
            for record in records:
                if record.status != "STAGED":
                    errors.append({"record_id": record.record_id, "error": f"Record is no longer staged: {record.status}."})
                    continue
                try:
                    _, was_created = self._promote_record_in_session(session, record, now, actor)
                    processed += 1
                    created += int(was_created)
                    reused += int(not was_created)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "error": str(exc)})
            session.commit()
        return {"processed": processed, "created": created, "reused": reused, "failed": len(errors), "errors": errors}

    def promote_ingestion_record(self, record_id: str, actor: str) -> str:
        """Create a pending worker and engagement from one staged record.

        This is explicit and reversible through the normal review/publication flow;
        the file watcher never calls it automatically.
        """
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            record = session.get(IngestionRecordModel, record_id)
            if record is None:
                raise ValueError("Ingestion record was not found.")
            if record.status not in {"STAGED", "MATCHED"}:
                raise ValueError(f"Ingestion record cannot be promoted from status {record.status}.")
            worker_id, _ = self._promote_record_in_session(session, record, now, actor)
            return worker_id

    def merge_workers(self, survivor_worker_id: str, duplicate_worker_id: str, reason: str, actor: str) -> dict[str, object]:
        """Merge duplicate canonical profiles without destroying historical evidence."""
        reason = reason.strip()
        if not reason:
            raise ValueError("A merge reason is required.")
        if survivor_worker_id == duplicate_worker_id:
            raise ValueError("The survivor and duplicate must be different workers.")
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            survivor = session.get(WorkerModel, survivor_worker_id)
            duplicate = session.get(WorkerModel, duplicate_worker_id)
            if survivor is None or duplicate is None:
                raise ValueError("Both workers must exist before merging.")
            if duplicate.superseded_by_worker_id:
                raise ValueError("The duplicate worker has already been superseded.")
            moved = {"identifiers": 0, "engagements": 0, "lineage": 0, "discrepancies": 0, "ingestion_records": 0}
            survivor_keys = {(item.source_system, item.identifier_type, item.normalized_value) for item in session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == survivor_worker_id)).all()}
            for item in session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == duplicate_worker_id)).all():
                key = (item.source_system, item.identifier_type, item.normalized_value)
                if key in survivor_keys:
                    item.active = False
                    continue
                item.worker_id = survivor_worker_id
                survivor_keys.add(key)
                moved["identifiers"] += 1
            for model, key in ((WorkerEngagementModel, "engagements"), (WorkerSourceLineageModel, "lineage"), (WorkerDiscrepancyModel, "discrepancies")):
                for item in session.scalars(select(model).where(model.worker_id == duplicate_worker_id)).all():
                    item.worker_id = survivor_worker_id
                    moved[key] += 1
            for record in session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.matched_worker_id == duplicate_worker_id)).all():
                record.matched_worker_id = survivor_worker_id
                moved["ingestion_records"] += 1
            survivor_profile_keys = {(item.source_system, item.source_record_key) for item in session.scalars(select(WorkerSourceProfileModel).where(WorkerSourceProfileModel.worker_id == survivor_worker_id)).all()}
            for profile in session.scalars(select(WorkerSourceProfileModel).where(WorkerSourceProfileModel.worker_id == duplicate_worker_id)).all():
                key = (profile.source_system, profile.source_record_key)
                if key in survivor_profile_keys:
                    profile.status = "SUPERSEDED"
                    continue
                profile.worker_id = survivor_worker_id
                survivor_profile_keys.add(key)
            duplicate.status = "DUPLICATE_SUPERSEDED"
            duplicate.superseded_by_worker_id = survivor_worker_id
            duplicate.updated_at_utc = now
            session.add(WorkerMergeEventModel(merge_id=str(uuid.uuid4()), survivor_worker_id=survivor_worker_id, duplicate_worker_id=duplicate_worker_id, reason=reason, actor=actor, created_at_utc=now))
            record_worker_version(session, survivor_worker_id, actor=actor, change_type="MERGE_SURVIVOR", changed_fields=["identifiers", "engagements", "lineage", "discrepancies"])
            record_worker_version(session, duplicate_worker_id, actor=actor, change_type="MERGE_SUPERSEDED", changed_fields=["status", "superseded_by_worker_id"])
            return {"survivor_worker_id": survivor_worker_id, "duplicate_worker_id": duplicate_worker_id, "moved": moved}
