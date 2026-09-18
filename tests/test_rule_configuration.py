from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iam_automation import webapp
from iam_automation.application.business_calendar import configured_rule_calendar
from iam_automation.application.rule_configuration_service import RuleConfigurationService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN
from iam_automation.infrastructure.sqlite.orm import DimFieldModel, orm_session
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class RuleConfigurationTests(unittest.TestCase):
    def make_result(self, database: Path) -> PreflightResult:
        root = database.parent / "sharepoint"
        settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
        return PreflightResult(StartupState.READY, True, "ready", settings)

    def test_default_context_and_calendar_are_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            configuration = RuleConfigurationService(database).configuration()

            self.assertEqual(configuration["context"].context_key, "DEFAULT")
            self.assertEqual(configuration["context_version"].missing_data_behavior, "FINDING")
            self.assertEqual(configuration["calendars"][0]["weekdays"], [0, 1, 2, 3, 4])
            self.assertEqual(configuration["calendars"][0]["holidays"], [])

    def test_calendar_and_context_changes_create_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RuleConfigurationService(database)
            calendar = service.configuration()["calendars"][0]["model"]

            calendar_result = service.save_calendar(
                calendar_id=calendar.calendar_id,
                label="Guatemala operations",
                timezone_name="America/Guatemala",
                weekdays=["0", "1", "2", "3", "4"],
                holidays="2026-09-15|Independence Day\n2026-12-25|Christmas|true",
                actor="admin",
            )
            context_result = service.save_context(
                calendar_id=calendar.calendar_id,
                timezone_name="America/Guatemala",
                missing_data_behavior="SKIP",
                date_boundary="INCLUSIVE_BOTH",
                actor="admin",
            )
            configuration = service.configuration()

            self.assertEqual(calendar_result["version"], 2)
            self.assertEqual(context_result["version"], 2)
            self.assertEqual(configuration["calendars"][0]["version"].version, 2)
            self.assertEqual(len(configuration["calendars"][0]["holidays"]), 2)
            self.assertEqual(configuration["context_version"].timezone, "America/Guatemala")
            self.assertEqual(configuration["context_version"].missing_data_behavior, "SKIP")
            self.assertEqual(
                configuration["context_version"].default_calendar_version_id,
                configuration["calendars"][0]["version"].calendar_version_id,
            )

    def test_context_keeps_using_the_pinned_calendar_version_after_calendar_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RuleConfigurationService(database)
            calendar = service.configuration()["calendars"][0]["model"]
            initial_context_version = service.configuration()["context_version"].context_version_id

            service.save_calendar(
                calendar_id=calendar.calendar_id,
                label="Monday only",
                timezone_name="UTC",
                weekdays=["0"],
                holidays="",
                actor="admin",
            )

            pinned = service.configuration()["context_version"]
            self.assertEqual(pinned.context_version_id, initial_context_version)
            self.assertEqual(pinned.default_calendar_version_id, "calendar:standard:1")
            self.assertEqual(
                configured_rule_calendar(database, context_version_id=pinned.context_version_id).operating_weekdays,
                frozenset({0, 1, 2, 3, 4}),
            )

    def test_field_metadata_updates_type_and_rule_operators(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                field = session.query(DimFieldModel).filter_by(field_key="termination_date").one()
                field.label = "Termination date"
                field_id = field.field_id

            result = RuleConfigurationService(database).update_field(
                field_id=field_id,
                data_type="DATE",
                nullable=False,
                rule_enabled=True,
                normalization_name="parse_date",
                actor="admin",
            )
            item = next(item for item in RuleConfigurationService(database).configuration()["fields"] if item["model"].field_id == field_id)

            self.assertEqual(result["version"], 2)
            self.assertEqual(item["data_type"], "DATE")
            self.assertIn("between", item["operators"])
            self.assertFalse(item["model"].nullable)

    @patch("iam_automation.application.rules.configuration.fetch_public_holidays")
    def test_imported_holidays_are_added_and_can_be_disabled(self, fetch_holidays):
        fetch_holidays.return_value = [{
            "date": "2026-07-04", "label": "Independence Day", "source": "NAGER_DATE",
            "country": "US", "year": 2026, "type": "Public", "observed_date": "2026-07-03", "enabled": True,
        }]
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RuleConfigurationService(database)
            calendar = service.configuration()["calendars"][0]["model"]

            result = service.import_holidays(calendar_id=calendar.calendar_id, country_code="us", year=2026, actor="admin")
            imported = service.configuration()["calendars"][0]["holidays"]
            service.save_calendar(
                calendar_id=calendar.calendar_id,
                label="Standard operating calendar",
                timezone_name="UTC",
                weekdays=["0", "1", "2", "3", "4"],
                holidays="",
                holiday_rows=[{
                    "date": item.holiday_date, "label": item.label, "source": item.source,
                    "country": item.source_country, "year": item.source_year, "type": item.holiday_type,
                    "observed_date": item.observed_date, "enabled": False,
                } for item in imported],
                actor="admin",
            )

            self.assertEqual(result["imported"], 1)
            self.assertTrue(imported[0].enabled)
            self.assertFalse(RuleConfigurationService(database).configuration()["calendars"][0]["holidays"][0].enabled)
            fetch_holidays.assert_called_once_with("US", 2026)

    def test_admin_can_open_and_save_rule_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
            app = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: admin)
            client = app.test_client()
            client.get("/admin/business-rules/config")
            with client.session_transaction() as session:
                session["iam_user"] = admin.username
                session["iam_roles"] = list(admin.roles)
                csrf_token = session["iam_csrf_token"]
            headers = {"X-CSRF-Token": csrf_token}

            page = client.get("/admin/business-rules/config")
            response = client.post(
                "/admin/business-rules/config",
                data={
                    "section": "context",
                    "calendar_id": "calendar:standard",
                    "timezone": "America/Guatemala",
                    "missing_data_behavior": "FINDING",
                    "date_boundary": "EXCLUSIVE_START_INCLUSIVE_END",
                },
                headers=headers,
            )

            self.assertEqual(page.status_code, 200)
            self.assertIn(b"Rule configuration", page.data)
            self.assertIn(b"Import public holidays", page.data)
            self.assertIn(b"Enabled", page.data)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Rule context saved as version 2", response.data)


if __name__ == "__main__":
    unittest.main()
