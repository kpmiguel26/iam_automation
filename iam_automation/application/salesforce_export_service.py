from __future__ import annotations

import shutil
from copy import copy
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select

from ..infrastructure.sqlite.orm import ChangeRequestModel, orm_session
from .audit_service import record_audit


DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "docs" / "req" / "salesforce_template" / "SF PROD TEMPLATE -- KPMA RITM2254022 2025_08_13.xlsx"
EXPORT_FILENAME_PREFIX = "Salesforce_User_Bulk"


class SalesforceExportService:
    """Builds a Salesforce Data Loader workbook from approved local IAM requests."""

    def __init__(self, database_path: Path, *, audit_path: Path | None = None, template_path: Path | None = None):
        self.database_path = database_path
        self.audit_path = audit_path
        self.template_path = template_path or DEFAULT_TEMPLATE_PATH

    def generate(self, destination_folder: Path, actor: str) -> Path:
        if not self.template_path.is_file():
            raise ValueError(f"Salesforce template was not found: {self.template_path}")
        rows = self._approved_employee_rows()
        if not rows:
            raise ValueError("No approved employee requests are available for Salesforce export.")

        destination_folder.mkdir(parents=True, exist_ok=True)
        destination = destination_folder / f"{EXPORT_FILENAME_PREFIX}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
        shutil.copy2(self.template_path, destination)
        workbook = load_workbook(destination)
        worksheet = workbook.active
        headers = {str(cell.value).strip().upper(): cell.column for cell in worksheet[2] if cell.value}
        template_row = 3
        # Keep the official workbook's formulas, widths and default values, but remove sample people.
        for row_number in range(template_row, worksheet.max_row + 1):
            for column_number in range(1, worksheet.max_column + 1):
                worksheet.cell(row_number, column_number).value = None

        for offset, payload in enumerate(rows):
            row_number = template_row + offset
            if row_number > worksheet.max_row:
                self._copy_row_style(worksheet, template_row, row_number)
            self._write_row(worksheet, row_number, headers, payload)
        workbook.save(destination)
        record_audit(self.audit_path, actor, "SALESFORCE_TEMPLATE_GENERATED", "salesforce_export", destination.name, new_values={"rows": len(rows), "source": "approved_sqlite_requests", "template": self.template_path.name})
        return destination

    def _approved_employee_rows(self) -> list[dict[str, object]]:
        with orm_session(self.database_path) as session:
            requests = session.scalars(select(ChangeRequestModel).where(ChangeRequestModel.status == "APPROVED", ChangeRequestModel.operation_type.in_(("CREATE_EMPLOYEE", "UPDATE_EMPLOYEE"))).order_by(ChangeRequestModel.updated_at_utc.asc())).all()
        latest: dict[str, dict[str, object]] = {}
        for request in requests:
            payload = json_loads(request.payload_json)
            payload.setdefault("employee_id", request.entity_id)
            payload.setdefault("entity_id", request.entity_id)
            latest[request.entity_id] = payload
        return list(latest.values())

    @staticmethod
    def _copy_row_style(worksheet, source_row: int, target_row: int) -> None:
        worksheet.row_dimensions[target_row].height = worksheet.row_dimensions[source_row].height
        for column_number in range(1, worksheet.max_column + 1):
            source = worksheet.cell(source_row, column_number)
            target = worksheet.cell(target_row, column_number)
            if source.has_style:
                target._style = copy(source._style)
            if source.number_format:
                target.number_format = source.number_format

    @staticmethod
    def _write_row(worksheet, row_number: int, headers: dict[str, int], payload: dict[str, object]) -> None:
        values = {str(key).strip().upper(): value for key, value in payload.items()}
        first_name = text(values, "FIRST_NAME", "FIRSTNAME", "GIVEN_NAME")
        last_name = text(values, "LAST_NAME", "LASTNAME", "SURNAME")
        email = text(values, "EMAIL", "EMAIL_ADDRESS", "KP_EMAIL")
        username = text(values, "USERNAME", "USER_NAME", "APPLICATION_USERNAME") or email
        employee_id = text(values, "EMPLOYEE_ID", "ENTITY_ID", "WORKER_ID", "NUID")
        alias = text(values, "ALIAS") or (f"{first_name[:1]}{last_name[:4]}".lower() if first_name and last_name else "")
        mapped = {
            "ID": text(values, "SALESFORCE_ID", "ID"),
            "USERNAME": username,
            "LASTNAME": last_name,
            "FIRSTNAME": first_name,
            "DIVISION": text(values, "DIVISION", "LOB", "LINE_OF_BUSINESS"),
            "DEPARTMENT": text(values, "DEPARTMENT"),
            "COUNTRY": text(values, "COUNTRY") or "United States",
            "COUNTRYCODE": text(values, "COUNTRY_CODE", "COUNTRYCODE") or "US",
            "EMAIL": email or username,
            "ALIAS": alias,
            "ISACTIVE": boolean_value(values.get("ISACTIVE", values.get("ACTIVE", True))),
            "TIMEZONESIDKEY": text(values, "TIMEZONE", "TIMEZONESIDKEY") or "America/Los_Angeles",
            "LOCALESIDKEY": text(values, "LOCALE", "LOCALESIDKEY") or "en_US",
            "EMPLOYEENUMBER": employee_id,
            "FEDERATIONIDENTIFIER": text(values, "FEDERATION_IDENTIFIER", "FEDERATIONIDENTIFIER") or username,
            "NUID__C": employee_id,
            "AGENT_NPN__C": text(values, "AGENT_NPN", "AGENT_NPN__C"),
            "CLASS_DETAIL_LOB__C": text(values, "CLASS_DETAIL_LOB", "CLASS_DETAIL_LOB__C"),
            "CLASS_TIER__C": text(values, "CLASS_TIER", "CLASS_TIER__C"),
            "BILLING_CODE__C": text(values, "BILLING_CODE", "BILLING_CODE__C"),
            "CCENTER__C": text(values, "CCENTER", "CCENTER__C"),
        }
        for header, column_number in headers.items():
            if header in {"NAME"}:
                worksheet.cell(row_number, column_number).value = f'=CONCATENATE(D{row_number}," ",C{row_number})'
            elif header in mapped:
                worksheet.cell(row_number, column_number).value = mapped[header]


def text(values: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def boolean_value(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "inactive"}
    return bool(value)


def json_loads(value: str) -> dict[str, object]:
    import json

    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
