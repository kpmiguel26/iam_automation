"""Migrate legacy worker JSON snapshots into relational star facts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..infrastructure.sqlite.orm import (
    EmployeeFieldValueModel,
    FactWorkerFieldHistoryModel,
    FieldCatalogModel,
    WorkerProfileVersionModel,
    WorkerSourceProfileModel,
    orm_session,
)
from .employee_field_projection_service import EmployeeFieldProjectionService
from .publication_state import mark_publication_pending


class LegacyStarMigrationService:
    """Convert legacy JSON snapshots and leave the old rows structurally intact."""

    def __init__(self, database_path: Path, backup_directory: Path | None = None):
        self.database_path = database_path.expanduser().resolve()
        self.backup_directory = (backup_directory or self.database_path.parent / "backups").expanduser().resolve()

    def migrate(self, actor: str) -> dict[str, object]:
        if not self.database_path.is_file():
            raise ValueError(f"Runtime SQLite database was not found: {self.database_path}")
        backup = self._backup_database()
        now = datetime.now(timezone.utc).isoformat()
        versions = profiles = fields = history = 0
        with orm_session(self.database_path) as session:
            for item in session.scalars(select(WorkerProfileVersionModel).order_by(WorkerProfileVersionModel.created_at_utc, WorkerProfileVersionModel.version_number)).all():
                payload = self._payload(item.snapshot_json)
                written = self._write_history(session, str(item.worker_id), str(item.source_system or "CANONICAL"), int(item.version_number or 1), str(item.created_at_utc or now), str(item.source_file or ""), payload)
                history += written
                if payload:
                    versions += 1
                item.snapshot_json = ""
            for item in session.scalars(select(WorkerSourceProfileModel)).all():
                payload = self._payload(item.snapshot_json)
                fields += self._write_current(session, str(item.worker_id), str(item.source_system or "UNKNOWN"), str(item.source_record_key or ""), str(item.current_record_id or ""), str(item.last_seen_at_utc or now), payload)
                if payload:
                    profiles += 1
                item.snapshot_json = ""
        result = {"backup": str(backup), "profile_versions_migrated": versions, "source_profiles_migrated": profiles, "history_fields_written": history, "current_fields_written": fields}
        mark_publication_pending(self.database_path, actor=actor, reason="Legacy JSON worker snapshots migrated to star facts")
        return result

    @classmethod
    def _write_history(cls, session, worker_id: str, source_system: str, version: int, observed_at: str, source_file: str, payload: dict[str, object]) -> int:
        written = 0
        for field_key, raw_value in payload.items():
            field_key = str(field_key).strip().lower()
            if field_key not in EmployeeFieldProjectionService.PILOT_FIELDS:
                continue
            existing = session.scalar(select(FactWorkerFieldHistoryModel).where(FactWorkerFieldHistoryModel.worker_id == worker_id, FactWorkerFieldHistoryModel.source_system == source_system, FactWorkerFieldHistoryModel.field_key == field_key, FactWorkerFieldHistoryModel.version_number == version))
            if existing is None:
                session.add(FactWorkerFieldHistoryModel(history_id=str(uuid.uuid4()), worker_id=worker_id, source_system=source_system, field_key=field_key, value_text=str(raw_value or "").strip(), version_number=version, observed_at_utc=observed_at, source_file=source_file))
                written += 1
        return written

    @classmethod
    def _write_current(cls, session, worker_id: str, source_system: str, source_record_key: str, source_record_id: str, observed_at: str, payload: dict[str, object]) -> int:
        written = 0
        for field_key, raw_value in payload.items():
            field_key = str(field_key).strip().lower()
            if field_key not in EmployeeFieldProjectionService.PILOT_FIELDS:
                continue
            catalog = session.get(FieldCatalogModel, field_key)
            if catalog is None:
                catalog = FieldCatalogModel(field_key=field_key, label=field_key.replace("_", " ").title(), created_at_utc=observed_at, updated_at_utc=observed_at)
                session.add(catalog)
                session.flush()
            current = session.scalar(select(EmployeeFieldValueModel).where(EmployeeFieldValueModel.worker_id == worker_id, EmployeeFieldValueModel.source_system == source_system, EmployeeFieldValueModel.field_key == field_key))
            if current is None:
                current = EmployeeFieldValueModel(value_id=str(uuid.uuid4()), worker_id=worker_id, source_system=source_system, field_key=field_key)
                session.add(current)
            current.value_text = str(raw_value or "").strip()
            current.source_record_key = source_record_key
            current.source_record_id = source_record_id
            current.observed_at_utc = observed_at
            current.updated_at_utc = observed_at
            written += 1
        return written

    @staticmethod
    def _payload(raw: str | None) -> dict[str, object]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _backup_database(self) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.backup_directory / f"before-star-legacy-migration-{stamp}.sqlite"
        source = sqlite3.connect(self.database_path, timeout=30)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        return destination
