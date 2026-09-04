"""Maintain the compact, governed current employee field projection."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ..infrastructure.sqlite.orm import EmployeeFieldValueModel, FieldCatalogModel


class EmployeeFieldProjectionService:
    """Project only approved fields; source JSON remains audit evidence for now."""

    PILOT_FIELDS = {
        "employee_id", "accessnow_employee_id", "accessnow_nuid", "vendor_employee_id", "work_order_id", "npn",
        "first_name", "last_name", "full_name", "email", "work_email", "personal_email", "phone",
        "status", "accessnow_status", "termination_date", "terminated_date", "hire_date", "start_date",
        "vendor_name", "supervisor_name", "manager_name", "job_title", "country", "site_location",
    }

    @classmethod
    def project_record_in_session(cls, session, record, worker_id: str, now: str | None = None) -> int:
        observed_at = now or datetime.now(timezone.utc).isoformat()
        payload = json.loads(record.normalized_json or "{}")
        count = 0
        for field_key, raw_value in payload.items():
            field_key = str(field_key).strip().lower()
            if field_key not in cls.PILOT_FIELDS:
                continue
            value = str(raw_value or "").strip()
            catalog = session.get(FieldCatalogModel, field_key)
            if catalog is None:
                catalog = FieldCatalogModel(field_key=field_key, label=field_key.replace("_", " ").title(), created_at_utc=observed_at, updated_at_utc=observed_at)
                session.add(catalog)
            else:
                catalog.updated_at_utc = observed_at
            current = session.scalar(select(EmployeeFieldValueModel).where(
                EmployeeFieldValueModel.worker_id == worker_id,
                EmployeeFieldValueModel.source_system == record.source_system,
                EmployeeFieldValueModel.field_key == field_key,
            ))
            if current is None:
                current = EmployeeFieldValueModel(value_id=str(uuid.uuid4()), worker_id=worker_id, source_system=record.source_system, field_key=field_key)
                session.add(current)
            current.value_text = value
            current.source_record_key = record.source_record_key
            current.source_record_id = record.record_id
            current.observed_at_utc = observed_at
            current.updated_at_utc = observed_at
            count += 1
        return count
