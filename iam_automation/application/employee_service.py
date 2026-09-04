"""
File: iam_automation/application/employee_service.py
Purpose: Implements the application service for employee service workflows.
Responsibilities: Exposes or coordinates: EmployeeSummary, EmployeeService.
Dependencies: sqlalchemy, infrastructure, worker_history_service, publication_state, source_reconciliation
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, case, func, not_, or_, select

from ..infrastructure.sqlite.orm import (
    ImportBatchModel,
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
from .employee_field_projection_service import EmployeeFieldProjectionService
from .publication_state import mark_publication_pending
from .source_reconciliation import ensure_source_identifiers, find_worker_matches, reconcile_worker_status_in_session
from .rehire_alert_service import RehireAlertService
from .star_schema_writer import StarSchemaWriter


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
    last_updated_at_utc: str = ""
    change_type: str = "UPDATED"


CANONICAL_DUPLICATE_REPORT_COLUMNS = (
    "group", "survivor_worker_id", "duplicate_worker_id", "survivor_name",
    "duplicate_name", "status", "conflict_count", "conflicts", "sources",
    "files", "observed_dates", "recommendation",
)


class EmployeeService:
    """Read canonical workers and explicitly promote staged source records."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _source_file_name(value: object) -> str:
        """Return a portable basename for records created on any OS."""
        return Path(str(value or "").replace("\\", "/")).name

    @staticmethod
    def _source_file_modified_at(value: object) -> str:
        """Return the source workbook modification time when this workspace can access it."""
        try:
            return datetime.fromtimestamp(Path(str(value or "")).stat().st_mtime, timezone.utc).isoformat()
        except (OSError, ValueError):
            return ""

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

    def list_workers(self, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "", review: str = "", updated: str = "ALL", sort: str = "UPDATED_DESC") -> list[EmployeeSummary]:
        """Return the full directory for internal callers and small datasets."""
        workers, _ = self.list_workers_page(search=search, status=status, vendor=vendor, source=source, engagement=engagement, review=review, updated=updated, sort=sort, page=1, per_page=None)
        return workers

    @staticmethod
    def _directory_change_type(worker_status: str, engagement_status: str, latest_change_type: str) -> str:
        """Classify the latest canonical activity for the directory badge."""
        statuses = f"{worker_status} {engagement_status}".replace("_", " ").replace("-", " ").upper()
        change = str(latest_change_type or "").upper()
        if any(token in statuses for token in ("TERMINAT", "DEACTIVAT", "INACTIVE")):
            return "TERMINATION"
        if change.endswith("_INITIAL_PROFILE"):
            return "NEW_HIRE"
        if "NEW HIRE" in statuses and not change:
            return "NEW_HIRE"
        if change:
            return "UPDATED"
        return "NO_CHANGE"

    def list_workers_page(self, *, search: str = "", status: str = "ALL", vendor: str = "ALL", source: str = "ALL", engagement: str = "", review: str = "", updated: str = "ALL", sort: str = "UPDATED_DESC", page: int = 1, per_page: int | None = 25) -> tuple[list[EmployeeSummary], int]:
        """Query only one directory page; filtering stays in SQLite."""
        search = search.strip()
        engagement = engagement.strip()
        updated = updated.strip().upper() or "ALL"
        sort = sort.strip().upper() or "UPDATED_DESC"
        if sort not in {"UPDATED_DESC", "UPDATED_ASC", "NAME_ASC", "NAME_DESC"}:
            sort = "UPDATED_DESC"
        page = max(1, int(page))
        if per_page is not None:
            per_page = max(1, min(int(per_page), 100))
        with orm_session(self.database_path) as session:
            filters = []
            latest_engagement = select(func.max(WorkerEngagementModel.updated_at_utc)).where(WorkerEngagementModel.worker_id == WorkerModel.worker_id).correlate(WorkerModel).scalar_subquery()
            latest_history = select(func.max(WorkerProfileVersionModel.created_at_utc)).where(WorkerProfileVersionModel.worker_id == WorkerModel.worker_id).correlate(WorkerModel).scalar_subquery()
            latest_change_type = select(WorkerProfileVersionModel.change_type).where(
                WorkerProfileVersionModel.worker_id == WorkerModel.worker_id,
            ).order_by(
                WorkerProfileVersionModel.created_at_utc.desc(),
                WorkerProfileVersionModel.version_number.desc(),
            ).limit(1).correlate(WorkerModel).scalar_subquery()
            last_updated = func.max(
                WorkerModel.updated_at_utc,
                func.coalesce(latest_engagement, ""),
                func.coalesce(latest_history, ""),
            )
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
            update_windows = {
                "LAST_24_HOURS": timedelta(hours=24),
                "LAST_7_DAYS": timedelta(days=7),
                "LAST_30_DAYS": timedelta(days=30),
                "LAST_90_DAYS": timedelta(days=90),
            }
            if updated in update_windows:
                updated_since = (datetime.now(timezone.utc) - update_windows[updated]).isoformat()
                filters.append(last_updated >= updated_since)
            filters.append(WorkerModel.superseded_by_worker_id.is_(None))
            sort_order = {
                "UPDATED_DESC": (last_updated.desc(), WorkerModel.display_name, WorkerModel.worker_id),
                "UPDATED_ASC": (last_updated.asc(), WorkerModel.display_name, WorkerModel.worker_id),
                "NAME_ASC": (WorkerModel.display_name, WorkerModel.worker_id),
                "NAME_DESC": (WorkerModel.display_name.desc(), WorkerModel.worker_id),
            }[sort]
            statement = select(WorkerModel, last_updated.label("last_updated_at_utc"), latest_change_type.label("latest_change_type")).where(*filters).order_by(*sort_order)
            total = int(session.scalar(select(func.count()).select_from(WorkerModel).where(*filters)) or 0)
            if per_page is not None:
                statement = statement.offset((page - 1) * per_page).limit(per_page)
            worker_rows = session.execute(statement).all()
            result: list[EmployeeSummary] = []
            for worker, last_updated_at, worker_change_type in worker_rows:
                engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker.worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
                identifier = session.scalar(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker.worker_id, WorkerIdentifierModel.active.is_(True)).order_by(WorkerIdentifierModel.created_at_utc))
                discrepancy_count = session.scalar(select(func.count()).select_from(WorkerDiscrepancyModel).where(WorkerDiscrepancyModel.worker_id == worker.worker_id, WorkerDiscrepancyModel.status == "OPEN")) or 0
                change_type = self._directory_change_type(worker.status, engagement.status if engagement else "", worker_change_type or "")
                result.append(EmployeeSummary(worker.worker_id, worker.display_name, worker.canonical_email, worker.status, identifier.identifier_value if identifier else "", engagement.vendor_name if engagement else "", engagement.job_title if engagement else "", identifier.source_system if identifier else "", int(discrepancy_count), str(last_updated_at or ""), change_type))
            return result, total

    def filter_values(self) -> tuple[list[str], list[str], list[str]]:
        with orm_session(self.database_path) as session:
            statuses = list(session.scalars(select(WorkerModel.status).where(WorkerModel.status.is_not(None), func.trim(WorkerModel.status) != "").distinct().order_by(WorkerModel.status)).all())
            vendors = list(session.scalars(select(WorkerEngagementModel.vendor_name).where(WorkerEngagementModel.vendor_name.is_not(None), func.trim(WorkerEngagementModel.vendor_name) != "").distinct().order_by(WorkerEngagementModel.vendor_name)).all())
            sources = list(session.scalars(select(WorkerIdentifierModel.source_system).where(WorkerIdentifierModel.active.is_(True), WorkerIdentifierModel.source_system.is_not(None), func.trim(WorkerIdentifierModel.source_system) != "").distinct().order_by(WorkerIdentifierModel.source_system)).all())
            return statuses, vendors, sources

    def list_canonical_duplicates(self) -> list[dict[str, object]]:
        """Return active canonical-worker groups sharing a normalized full name.

        This intentionally does not inspect staged source rows. A group is a
        merge candidate only when it contains more than one canonical worker
        record; source-file duplicates remain in the source-review workflow.
        """
        with orm_session(self.database_path) as session:
            workers = session.scalars(select(WorkerModel).where(
                WorkerModel.superseded_by_worker_id.is_(None),
            ).order_by(WorkerModel.display_name, WorkerModel.worker_id)).all()
            groups: dict[str, list[WorkerModel]] = {}
            for worker in workers:
                name_key = " ".join(f"{worker.first_name or ''} {worker.last_name or ''}".split()).casefold()
                if name_key:
                    groups.setdefault(name_key, []).append(worker)
            duplicate_members = [worker for members in groups.values() if len(members) >= 2 for worker in members]
            duplicate_ids = [worker.worker_id for worker in duplicate_members]
            identifiers_by_worker: dict[str, list[WorkerIdentifierModel]] = {}
            engagements_by_worker: dict[str, list[WorkerEngagementModel]] = {}
            lineage_by_worker: dict[str, list[WorkerSourceLineageModel]] = {}
            if duplicate_ids:
                for item in session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id.in_(duplicate_ids), WorkerIdentifierModel.active.is_(True)).order_by(WorkerIdentifierModel.source_system, WorkerIdentifierModel.identifier_type)).all():
                    identifiers_by_worker.setdefault(item.worker_id, []).append(item)
                for item in session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id.in_(duplicate_ids)).order_by(WorkerEngagementModel.source_system, WorkerEngagementModel.created_at_utc)).all():
                    engagements_by_worker.setdefault(item.worker_id, []).append(item)
                for item in session.scalars(select(WorkerSourceLineageModel).where(WorkerSourceLineageModel.worker_id.in_(duplicate_ids)).order_by(WorkerSourceLineageModel.observed_at_utc.desc())).all():
                    lineage_by_worker.setdefault(item.worker_id, []).append(item)
            result: list[dict[str, object]] = []
            for name_key, members in groups.items():
                if len(members) < 2:
                    continue
                result.append({
                    "name_key": name_key,
                    "display_name": members[0].display_name or " ".join(f"{members[0].first_name or ''} {members[0].last_name or ''}".split()),
                    "count": len(members),
                    "workers": [self._canonical_duplicate_summary_from_rows(worker, identifiers_by_worker.get(worker.worker_id, []), engagements_by_worker.get(worker.worker_id, []), lineage_by_worker.get(worker.worker_id, [])) for worker in members],
                })
            return result

    def canonical_duplicate_review(self, worker_id: str) -> dict[str, object] | None:
        """Return the active canonical-name group containing ``worker_id``."""
        for group in self.list_canonical_duplicates():
            if any(str(item["worker_id"]) == worker_id for item in group["workers"]):
                return group
        return None

    @staticmethod
    def _canonical_profile_completeness(worker: dict[str, object]) -> int:
        """Score the amount of durable information available on a profile."""
        identifiers = list(worker.get("identifiers") or [])
        engagements = list(worker.get("engagements") or [])
        engagement_fields = sum(
            sum(bool(str(item.get(field) or "").strip()) for field in (
                "vendor_name", "job_title", "status", "work_order_id",
                "source_file", "observed_at_utc",
            ))
            for item in engagements
        )
        return (
            (10 if str(worker.get("email") or "").strip() else 0)
            + (3 if str(worker.get("status") or "").strip() else 0)
            + len(identifiers) * 5
            + len(engagements) * 4
            + len(worker.get("source_systems") or []) * 2
            + engagement_fields
        )

    def canonical_duplicate_merge_plan(self, worker_id: str) -> dict[str, object] | None:
        """Build a deterministic plan using the oldest canonical as identity."""
        review = self.canonical_duplicate_review(worker_id)
        if review is None:
            return None
        return self._canonical_duplicate_merge_plan_for_group(review)

    def _canonical_duplicate_merge_plan_for_group(self, review: dict[str, object]) -> dict[str, object]:
        """Build a merge plan from an already loaded duplicate group."""
        ranked = sorted(
            list(review["workers"]),
            key=lambda worker: (
                str(worker.get("created_at_utc") or ""),
                str(worker.get("worker_id") or ""),
            ),
        )
        field_names = (
            ("first_name", "First name"),
            ("last_name", "Last name"),
            ("email", "Email"),
            ("status", "Status"),
        )
        conflicts: list[dict[str, str]] = []
        for duplicate in ranked[1:]:
            for field, label in field_names:
                survivor_value = str(ranked[0].get(field) or "").strip()
                duplicate_value = str(duplicate.get(field) or "").strip()
                if not survivor_value or not duplicate_value or survivor_value.casefold() == duplicate_value.casefold():
                    continue
                conflicts.append({
                    "field": label,
                    "survivor_value": survivor_value,
                    "incoming_value": duplicate_value,
                    "source": ", ".join(duplicate.get("source_systems") or []) or "Profile history",
                    "observed_at": str(duplicate.get("updated_at_utc") or duplicate.get("created_at_utc") or ""),
                    "profile_id": str(duplicate.get("worker_id") or ""),
                })
        return {
            "survivor": ranked[0],
            "duplicates": ranked[1:],
            "selection_reason": "oldest_canonical_identity",
            "conflicts": conflicts,
        }

    def canonical_duplicate_report_rows(self) -> list[dict[str, str]]:
        """Return flat, read-only rows shared by the duplicate UI and exports."""
        rows: list[dict[str, str]] = []
        for group in self.list_canonical_duplicates():
            plan = self._canonical_duplicate_merge_plan_for_group(group)
            survivor = plan["survivor"]
            for duplicate in plan["duplicates"]:
                conflicts = [item for item in plan["conflicts"] if item["profile_id"] == duplicate["worker_id"]]
                evidence = [item for item in duplicate.get("engagements") or [] if item.get("source_file") or item.get("observed_at_utc")]
                files = sorted({str(item.get("source_file") or "") for item in evidence if item.get("source_file")})
                dates = sorted({str(item.get("observed_at_utc") or "") for item in evidence if item.get("observed_at_utc")}, reverse=True)
                rows.append({
                    "group": str(group["display_name"]),
                    "survivor_worker_id": str(survivor["worker_id"]),
                    "duplicate_worker_id": str(duplicate["worker_id"]),
                    "survivor_name": str(survivor.get("display_name") or ""),
                    "duplicate_name": str(duplicate.get("display_name") or ""),
                    "status": "CONFLICT_REVIEW" if conflicts else "CANDIDATE",
                    "conflict_count": str(len(conflicts)),
                    "conflicts": "; ".join(f"{item['field']}: {item['survivor_value']} / {item['incoming_value']}" for item in conflicts),
                    "sources": ", ".join(str(item) for item in duplicate.get("source_systems") or []),
                    "files": "; ".join(files),
                    "observed_dates": "; ".join(dates),
                    "recommendation": "Consolidate into oldest canonical; review conflicts first" if conflicts else "Consolidate into oldest canonical identity",
                })
        return rows

    @staticmethod
    def _canonical_duplicate_summary_from_rows(worker: WorkerModel, identifiers: list[WorkerIdentifierModel], engagements: list[WorkerEngagementModel], lineage_rows: list[WorkerSourceLineageModel]) -> dict[str, object]:
        lineage_sources = sorted({str(item.source_system) for item in lineage_rows if item.source_system})
        engagement_evidence = {}
        for item in lineage_rows:
            if item.engagement_id and item.engagement_id not in engagement_evidence:
                engagement_evidence[item.engagement_id] = {"source_file": EmployeeService._source_file_name(item.source_file), "observed_at_utc": item.observed_at_utc}
        return {
            "worker_id": worker.worker_id,
            "display_name": worker.display_name,
            "email": worker.canonical_email,
            "status": worker.status,
            "record_version": worker.record_version,
            "created_at_utc": worker.created_at_utc,
            "updated_at_utc": worker.updated_at_utc,
            "identifiers": [{"source_system": item.source_system, "identifier_type": item.identifier_type, "value": item.identifier_value} for item in identifiers],
            "engagements": [{"source_system": item.source_system, "vendor_name": item.vendor_name, "job_title": item.job_title, "status": item.status, "work_order_id": item.work_order_id, "source_file": engagement_evidence.get(item.engagement_id, {}).get("source_file", ""), "observed_at_utc": engagement_evidence.get(item.engagement_id, {}).get("observed_at_utc", item.updated_at_utc)} for item in engagements],
            "source_systems": sorted(set(lineage_sources) | {str(item.source_system) for item in identifiers}),
        }

    @staticmethod
    def _canonical_duplicate_summary(session, worker: WorkerModel) -> dict[str, object]:
        return EmployeeService._canonical_duplicate_summary_from_rows(
            worker,
            session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == worker.worker_id, WorkerIdentifierModel.active.is_(True)).order_by(WorkerIdentifierModel.source_system, WorkerIdentifierModel.identifier_type)).all(),
            session.scalars(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker.worker_id).order_by(WorkerEngagementModel.source_system, WorkerEngagementModel.created_at_utc)).all(),
            session.scalars(select(WorkerSourceLineageModel).where(WorkerSourceLineageModel.worker_id == worker.worker_id).order_by(WorkerSourceLineageModel.observed_at_utc.desc())).all(),
        )

    def list_staged_records(self) -> list[dict[str, str]]:
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS"))).order_by(IngestionRecordModel.created_at_utc.desc())).all()
            return [{"record_id": row.record_id, "batch_id": row.batch_id, "source_system": row.source_system, "source_record_key": row.source_record_key, "source_file": self._source_file_name(row.source_file), "status": row.status, "match_status": row.match_status, "matched_worker_id": row.matched_worker_id or "", "match_reason": row.match_reason, "payload": json.loads(row.normalized_json)} for row in rows]

    def pending_source_update_count(self) -> int:
        """Count staged source rows without loading their payloads."""
        with orm_session(self.database_path) as session:
            return int(session.scalar(select(func.count()).select_from(IngestionRecordModel).where(
                IngestionRecordModel.status.in_(("STAGED", "MATCHED", "CONFLICT", "UNMATCHED", "AMBIGUOUS")),
                IngestionRecordModel.observation_state.not_in(("CURRENT", "SUPERSEDED", "RESOLVED")),
            )) or 0)

    def rehire_alerts(self, source_file: str = "") -> list[dict[str, object]]:
        return RehireAlertService(self.database_path).list_alerts(source_file)

    def rehire_alert_count(self) -> int:
        return RehireAlertService(self.database_path).count()

    def rehire_alerts_for_worker(self, worker_id: str) -> list[dict[str, object]]:
        return RehireAlertService(self.database_path).list_for_worker(worker_id)

    def resolve_rehire_alert(self, record_id: str, actor: str, reason: str) -> dict[str, str]:
        return RehireAlertService(self.database_path).archive(record_id, actor, reason)

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
                    ImportBatchModel.source_modified_at_utc,
                ).join(ImportBatchModel, ImportBatchModel.batch_id == IngestionRecordModel.batch_id, isouter=True)
                .where(IngestionRecordModel.source_system == source_system)
                .order_by(ImportBatchModel.source_modified_at_utc.asc(), IngestionRecordModel.created_at_utc.asc())
            ).all()
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for source_file, checksum, status, match_status, observation_state, created_at, source_modified_at in rows:
            key = (self._source_file_name(source_file), str(checksum or ""))
            item = grouped.setdefault(key, {
                "source_system": source_system,
                "source_file": key[0],
                "source_path": str(source_file or ""),
                "source_checksum": key[1],
                "record_count": 0,
                "staged_count": 0,
                "pending_count": 0,
                "linked_count": 0,
                "ambiguous_count": 0,
                "conflict_count": 0,
                "superseded_count": 0,
                "latest_at": str(created_at or ""),
                "source_modified_at": str(source_modified_at or self._source_file_modified_at(source_file) or created_at or ""),
            })
            item["record_count"] = int(item["record_count"]) + 1
            if str(status) == "STAGED":
                item["staged_count"] = int(item["staged_count"]) + 1
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
        for item in grouped.values():
            staged_count = int(item["staged_count"])
            item["imported"] = bool(item["record_count"]) and staged_count == 0
            item["import_status"] = "IMPORTED" if item["imported"] else "READY_TO_IMPORT"
        return sorted(
            grouped.values(),
            key=lambda item: (
                str(item.get("source_modified_at") or item.get("latest_at") or ""),
                str(item.get("source_file") or "").casefold(),
            ),
        )

    def get_source_file_summary(self, source_system: str, source_file: str) -> dict[str, object] | None:
        files = self.list_source_files(source_system)
        return next((item for item in files if item["source_file"] == self._source_file_name(source_file)), None)

    def list_source_records(self, source_system: str, source_file: str, *, page: int = 1, per_page: int = 50, result_order: str = "RESULT", load_all: bool = False) -> tuple[list[dict[str, object]], int]:
        """Return one page of source rows, prioritizing the import outcome."""
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), 100))
        result_order = str(result_order or "RESULT").strip().upper()
        if result_order not in {"RESULT", "NEW_HIRES", "UPDATED", "CURRENT", "PENDING"}:
            result_order = "RESULT"
        file_summary = self.get_source_file_summary(source_system, source_file)
        if file_summary is None:
            return [], 0
        source_path = str(file_summary["source_path"])
        with orm_session(self.database_path) as session:
            base_filter = (
                IngestionRecordModel.source_system == source_system,
                IngestionRecordModel.source_file == source_path,
            )
            new_hire = or_(
                IngestionRecordModel.match_reason.ilike("%created during approval%"),
                and_(IngestionRecordModel.status == "APPLIED", IngestionRecordModel.matched_worker_id.is_(None)),
            )
            updated = and_(IngestionRecordModel.matched_worker_id.is_not(None), not_(new_hire))
            current = IngestionRecordModel.observation_state == "CURRENT"
            pending = not_(current)
            priority = {
                "RESULT": case((new_hire, 0), (updated, 1), (current, 2), else_=3),
                "NEW_HIRES": case((new_hire, 0), else_=1),
                "UPDATED": case((updated, 0), (new_hire, 1), (current, 2), else_=3),
                "CURRENT": case((current, 0), (new_hire, 1), (updated, 2), else_=3),
                "PENDING": case((pending, 0), (new_hire, 1), (updated, 2), else_=3),
            }[result_order]
            total = int(session.scalar(select(func.count()).select_from(IngestionRecordModel).where(
                *base_filter,
            )) or 0)
            statement = select(
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
                ).where(*base_filter).order_by(priority, IngestionRecordModel.created_at_utc.desc(), IngestionRecordModel.row_number)
            if not load_all:
                statement = statement.offset((page - 1) * per_page).limit(per_page)
            rows = session.execute(statement).all()
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
            import_result = self._source_import_result(row[4], row[6], row[7], row[8])
            result.append({
                "record_id": row[0], "batch_id": row[1], "source_system": row[2],
                "source_record_key": row[3], "worker_name": workers.get(row[7], ""),
                "status": row[4], "match_status": row[5], "match_reason": row[6],
                "matched_worker_id": row[7] or "", "observation_state": row[8] or "PENDING",
                "import_result": import_result, "created_at_utc": row[9], "payload": payload,
            })
        return result, total

    @staticmethod
    def _source_import_result(status: object, match_reason: object, matched_worker_id: object, observation_state: object) -> str:
        """Classify an imported row for the source-file review ordering."""
        reason = str(match_reason or "").casefold()
        if "created during approval" in reason or (str(status) == "APPLIED" and not matched_worker_id):
            return "NEW_HIRE"
        if matched_worker_id:
            return "UPDATED"
        if str(observation_state or "") == "CURRENT":
            return "CURRENT"
        return "PENDING"

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
        StarSchemaWriter.link_record_in_session(session, record, worker_id)
        EmployeeFieldProjectionService.project_record_in_session(session, record, worker_id, now)

    @staticmethod
    def _record_source_lineage_in_session(session, record: IngestionRecordModel, worker_id: str, now: str) -> None:
        """Attach every field in an immutable source row to the employee once."""
        payload = StarSchemaWriter.payload_for_record(session, record)
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
                payload = StarSchemaWriter.payload_for_record(session, row)
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

    def apply_approved_import_records(
        self,
        record_ids: list[str],
        actor: str,
        *,
        request_payload: dict[str, object] | None = None,
        progress_callback: Callable[[int, int, int, int, int], None] | None = None,
    ) -> dict[str, object]:
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
        progress_total = len(record_ids)
        progress_offset = 0
        progress_created = progress_reused = progress_failed = 0

        def report_progress(processed: int, total: int, created: int, reused: int, failed: int) -> None:
            if progress_callback is None:
                return
            progress_callback(
                min(progress_total, progress_offset + processed),
                progress_total,
                progress_created + created,
                progress_reused + reused,
                progress_failed + failed,
            )

        if rsr_ids:
            rsr_result = RsrSupplierWorkerDetailsAdapter(self.database_path).apply_approved_records(rsr_ids, actor, progress_callback=report_progress)
            self._sync_applied_source_profiles(rsr_ids)
            result["processed"] = int(result["processed"]) + int(rsr_result["processed"])
            result["created"] = int(result["created"]) + int(rsr_result.get("created", 0))
            result["reused"] = int(result["reused"]) + int(rsr_result.get("reused", 0))
            result["failed"] = int(result["failed"]) + int(rsr_result["failed"])
            result["errors"] = list(result["errors"]) + list(rsr_result["errors"])
            progress_offset += len(rsr_ids)
            progress_created += int(rsr_result.get("created", 0))
            progress_reused += int(rsr_result.get("reused", 0))
            progress_failed += int(rsr_result.get("failed", 0))
        if accessnow_ids:
            accessnow_result = AccessNowIngestionService(self.database_path).apply_approved_records(accessnow_ids, actor, progress_callback=report_progress)
            self._sync_applied_source_profiles(accessnow_ids)
            result["processed"] = int(result["processed"]) + int(accessnow_result["processed"])
            result["created"] = int(result["created"]) + int(accessnow_result.get("created", 0))
            result["reused"] = int(result["reused"]) + int(accessnow_result.get("reused", 0))
            result["failed"] = int(result["failed"]) + int(accessnow_result["failed"])
            result["errors"] = list(result["errors"]) + list(accessnow_result["errors"])
            progress_offset += len(accessnow_ids)
            progress_created += int(accessnow_result.get("created", 0))
            progress_reused += int(accessnow_result.get("reused", 0))
            progress_failed += int(accessnow_result.get("failed", 0))
        if roster_ids:
            roster_result = self.promote_staged_records(roster_ids, actor, progress_callback=report_progress)
            result["processed"] = int(result["processed"]) + int(roster_result["processed"])
            result["created"] = int(result["created"]) + int(roster_result["created"])
            result["reused"] = int(result["reused"]) + int(roster_result["reused"])
            result["failed"] = int(result["failed"]) + int(roster_result["failed"])
            result["errors"] = list(result["errors"]) + list(roster_result["errors"])
            progress_offset += len(roster_ids)
            progress_created += int(roster_result.get("created", 0))
            progress_reused += int(roster_result.get("reused", 0))
            progress_failed += int(roster_result.get("failed", 0))
        if progress_callback is not None:
            progress_callback(progress_total, progress_total, progress_created, progress_reused, progress_failed)
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
            old_status = str(worker.status or "")
            engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == worker_id).order_by(WorkerEngagementModel.updated_at_utc.desc()))
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(record_set), IngestionRecordModel.matched_worker_id == worker_id)).all()
            if not records:
                raise ValueError("The selected source records no longer match this employee.")
            for record in records:
                if record.status not in {"STAGED", "MATCHED", "CONFLICT"}:
                    continue
                payload = StarSchemaWriter.payload_for_record(session, record)
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
                    if owner == "worker" and attribute == "status":
                        # AccessNow status is source evidence. Reconcile it
                        # against dated observations below instead of applying
                        # the selected historical value directly to Worker.
                        continue
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
            reconcile_worker_status_in_session(session, worker_id)
            if old_status != worker.status:
                changed_fields.add("status")
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
            source_field_aliases = {
                "email": "canonical_email", "vendor_email": "canonical_email", "vendor_email_address": "canonical_email",
                "employee_first_name": "first_name", "employee_last_name": "last_name", "fg_status": "status",
                "accessnow_status": "status", "worker_status": "status", "worker_start_date": "onboarding_date",
                "worker_end_date": "production_start_date", "resident_license_state": "license_state",
                "resident_license_number": "license_number", "taxonomy": "taxonomy_code",
            }
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
                        canonical_field = source_field_aliases.get(field, field)
                        current_value = item["snapshot"].get(canonical_field, current_engagement.get(canonical_field, ""))
                        previous_value = previous.get(canonical_field, previous_engagement.get(canonical_field, ""))
                    if str(current_value or "").casefold() == str(previous_value or "").casefold():
                        continue
                    item["changes"].append({"field": field, "previous_value": previous_value or "Not set", "new_value": current_value or "Not set"})
                item["changed_fields"] = [change["field"] for change in item["changes"]]
            source_names = sorted({item.source_system for item in identifiers if item.source_system} | {item.source_system for item in engagements if item.source_system} | {item.source_system for item in lineage if item.source_system})
            lineage_by_engagement: dict[str, WorkerSourceLineageModel] = {}
            for item in lineage:
                if item.engagement_id and item.engagement_id not in lineage_by_engagement:
                    lineage_by_engagement[item.engagement_id] = item
            source_profiles = []
            for source_system in source_names:
                source_lineage = [item for item in lineage if item.source_system == source_system]
                latest_lineage = source_lineage[0] if source_lineage else None
                source_engagements = []
                for item in engagements:
                    if item.source_system != source_system:
                        continue
                    evidence = lineage_by_engagement.get(item.engagement_id)
                    source_engagements.append({
                        "source_system": item.source_system,
                        "vendor_name": item.vendor_name,
                        "program": item.program,
                        "project": item.project,
                        "supervisor_name": item.supervisor_name,
                        "job_title": item.job_title,
                        "country": item.country,
                        "site_location": item.site_location,
                        "onboarding_date": item.onboarding_date,
                        "production_start_date": item.production_start_date,
                        "status": item.status,
                        "source_file": self._source_file_name(evidence.source_file) if evidence else "",
                        "observed_at_utc": evidence.observed_at_utc if evidence else item.updated_at_utc,
                    })
                source_profiles.append({
                    "source_system": source_system,
                    "identifiers": [item for item in identifiers if item.source_system == source_system],
                    "engagements": source_engagements,
                    "lineage": source_lineage,
                    "source_file": self._source_file_name(latest_lineage.source_file) if latest_lineage else "",
                    "observed_at_utc": latest_lineage.observed_at_utc if latest_lineage else "",
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
                revalidated_ids: set[str] = set()
                for record, payload in zip(records, payloads):
                    matches, match_reason = find_worker_matches(session, record.source_system, payload)
                    if len(matches) > 1:
                        raise ValueError("The candidate dossier matches multiple canonical employees and requires manual resolution.")
                    if len(matches) == 1 and match_reason != "Canonical name match":
                        revalidated_ids.add(matches[0])
                if len(revalidated_ids) > 1:
                    raise ValueError("The candidate dossier matches more than one canonical employee.")
                if revalidated_ids:
                    worker_id = next(iter(revalidated_ids))
                    worker = session.get(WorkerModel, worker_id)
                if worker is not None:
                    for record in records:
                        record.matched_worker_id = worker_id
                        record.match_status = "MATCHED"
                        record.match_reason = "Canonical match revalidated during candidate preparation"
                    session.commit()
                    return {"worker_id": worker_id, "created": False, "record_ids": sorted(selected), "actor": actor}
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
        payload = StarSchemaWriter.payload_for_record(session, record)
        identifier_value = str(payload.get("vendor_employee_id") or payload.get("employee_number") or payload.get("nuid_login_id") or payload.get("npn_login_id") or "").strip()
        if not identifier_value and not record.matched_worker_id:
            raise ValueError("The staged record has no Vendor Employee ID.")

        matched_worker = session.get(WorkerModel, str(record.matched_worker_id)) if record.matched_worker_id else None
        matches, match_reason = find_worker_matches(session, record.source_system, payload)
        candidate_ids = set(matches)
        if matched_worker is not None and matched_worker.superseded_by_worker_id is None:
            candidate_ids.add(matched_worker.worker_id)
        if len(candidate_ids) > 1:
            raise ValueError("The staged source record matches multiple canonical employees and requires manual resolution.")
        worker = session.get(WorkerModel, next(iter(candidate_ids))) if candidate_ids else None
        if worker is not None and match_reason == "Canonical name match" and not identifier_value:
            raise ValueError("A name-only canonical match requires manual resolution.")
        created = worker is None
        if worker is None:
            worker_id = str(uuid.uuid4())
            employee_name = str(payload.get("employee_name") or "").strip()
            name_parts = employee_name.split()
            first_name = str(payload.get("first_name") or (name_parts[0] if name_parts else "")).strip()
            last_name = str(payload.get("last_name") or " ".join(name_parts[1:])).strip()
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
        else:
            worker_id = worker.worker_id
        old_status = str(worker.status or "")
        ensure_source_identifiers(session, worker_id, record.source_system, payload, now)

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
        reconcile_worker_status_in_session(session, worker_id)
        changed_fields = list(payload)
        if old_status != worker.status and "status" not in changed_fields:
            changed_fields.append("status")
        record_worker_version(
            session,
            worker_id,
            actor=actor,
            change_type=f"{record.source_system}_INITIAL_PROFILE" if created else f"{record.source_system}_ENRICHMENT",
            source_system=record.source_system,
            source_file=record.source_file,
            source_checksum=record.source_checksum,
            source_record_key=record.source_record_key,
            changed_fields=changed_fields,
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

    def promote_staged_records(
        self,
        record_ids: list[str],
        actor: str,
        *,
        progress_callback: Callable[[int, int, int, int, int], None] | None = None,
    ) -> dict[str, object]:
        """Apply only the records approved by an import request."""
        selected_ids = {str(record_id) for record_id in record_ids if str(record_id).strip()}
        if not selected_ids:
            raise ValueError("The import request contains no staged records.")
        now = datetime.now(timezone.utc).isoformat()
        processed = created = reused = 0
        errors: list[dict[str, str]] = []
        with orm_session(self.database_path) as session:
            records = session.scalars(select(IngestionRecordModel).where(IngestionRecordModel.record_id.in_(selected_ids))).all()
            handled = 0
            for record in records:
                if record.status != "STAGED":
                    errors.append({"record_id": record.record_id, "error": f"Record is no longer staged: {record.status}."})
                    handled += 1
                    if progress_callback:
                        progress_callback(handled, len(records), created, reused, len(errors))
                    continue
                try:
                    _, was_created = self._promote_record_in_session(session, record, now, actor)
                    processed += 1
                    created += int(was_created)
                    reused += int(not was_created)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append({"record_id": record.record_id, "error": str(exc)})
                handled += 1
                if progress_callback:
                    progress_callback(handled, len(records), created, reused, len(errors))
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
            merged_profile_fields: list[str] = []
            profile_conflicts = {"first_name", "last_name", "canonical_email", "status"}
            for field in profile_conflicts:
                survivor_value = str(getattr(survivor, field) or "").strip()
                duplicate_value = str(getattr(duplicate, field) or "").strip()
                if not survivor_value and duplicate_value and field != "status":
                    setattr(survivor, field, duplicate_value.lower() if field == "canonical_email" else duplicate_value)
                    merged_profile_fields.append(field)
                elif survivor_value and duplicate_value and survivor_value.casefold() != duplicate_value.casefold():
                    session.add(WorkerDiscrepancyModel(
                        discrepancy_id=str(uuid.uuid4()), worker_id=survivor_worker_id,
                        source_system="CANONICAL_MERGE", source_record_key=duplicate_worker_id,
                        field_name=field, current_value=survivor_value, incoming_value=duplicate_value,
                        status="OPEN", created_at_utc=now,
                    ))
                    moved["discrepancies"] += 1
            if "first_name" in merged_profile_fields or "last_name" in merged_profile_fields:
                survivor.display_name = " ".join(part for part in (survivor.first_name, survivor.last_name) if part)
                merged_profile_fields.append("display_name")
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
            record_worker_version(session, survivor_worker_id, actor=actor, change_type="MERGE_SURVIVOR", source_system="CANONICAL_MERGE", source_record_key=duplicate_worker_id, changed_fields=sorted(set(merged_profile_fields + ["identifiers", "engagements", "lineage", "discrepancies"])))
            record_worker_version(session, duplicate_worker_id, actor=actor, change_type="MERGE_SUPERSEDED", changed_fields=["status", "superseded_by_worker_id"])
            return {"survivor_worker_id": survivor_worker_id, "duplicate_worker_id": duplicate_worker_id, "moved": moved}
#endfile
