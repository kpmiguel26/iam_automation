from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from iam_automation.application.business_calendar import configured_rule_calendar
from iam_automation.application.condition_evaluator import ConditionEvaluator, ConditionValidationError
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    RuleCalendarHolidayModel,
    RuleCalendarVersionModel,
    orm_session,
)


class ConditionEvaluatorTests(unittest.TestCase):
    def test_legacy_condition_shape_remains_supported(self):
        evaluator = ConditionEvaluator()

        self.assertTrue(evaluator.matches({"field": "status", "operator": "equals", "value": "TERMINATED"}, {"status": "TERMINATED"}))
        self.assertTrue(evaluator.matches({"field": "email", "operator": "missing"}, {"email": ""}))
        self.assertFalse(evaluator.matches({"field": "email", "operator": "exists"}, {}))

    def test_explicit_operands_support_compound_conditions(self):
        condition = {
            "all": [
                {
                    "left": {"kind": "field", "source": "ACCESSNOW", "field": "accessnow_status"},
                    "operator": "in",
                    "right": {"kind": "literal", "value": ["TERMINATED", "DEACTIVATED"]},
                },
                {
                    "left": {"kind": "field", "source": "ROSTER_LOCK", "field": "email"},
                    "operator": "missing",
                    "right": {"kind": "literal", "value": None},
                },
            ]
        }
        payload = {"sources": {
            "ACCESSNOW": {"accessnow_status": "TERMINATED"},
            "ROSTER_LOCK": {"email": ""},
        }}

        self.assertTrue(ConditionEvaluator().matches(condition, payload))

    def test_business_days_derived_operand_uses_configured_calendar(self):
        condition = {
            "left": {
                "kind": "derived",
                "function": "business_days_between",
                "arguments": [
                    {"kind": "literal", "value": "2026-01-01"},
                    {"kind": "literal", "value": "2026-01-06"},
                ],
            },
            "operator": "between",
            "right": {"kind": "literal", "value": [1, 3]},
        }
        evaluator = ConditionEvaluator()
        self.assertTrue(evaluator.matches(condition, {}))

    def test_unknown_operator_is_rejected_for_operand_conditions(self):
        with self.assertRaises(ConditionValidationError):
            ConditionEvaluator().validate({
                "left": {"kind": "field", "field": "status"},
                "operator": "execute_sql",
                "right": {"kind": "literal", "value": "x"},
            })

    def test_database_calendar_controls_weekdays_and_holidays(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                version = session.query(RuleCalendarVersionModel).filter_by(calendar_version_id="calendar:standard:1").one()
                version.operating_weekdays_json = "[0,1,2,3,4]"
                session.add(RuleCalendarHolidayModel(
                    holiday_id="holiday-test", calendar_version_id=version.calendar_version_id,
                    holiday_date="2026-01-02", label="Configured closure", enabled=True,
                    recurring_annually=False, source="MANUAL", observed_date="2026-01-02",
                ))
            calendar = configured_rule_calendar(database)
            self.assertEqual(calendar.operating_weekdays, frozenset({0, 1, 2, 3, 4}))
            self.assertIn(date(2026, 1, 2), calendar.holidays_between(date(2026, 1, 1), date(2026, 1, 6)))
            self.assertEqual(
                ConditionEvaluator(calendar).matches({
                    "left": {"kind": "derived", "function": "business_days_between", "arguments": [
                        {"kind": "literal", "value": "2026-01-01"},
                        {"kind": "literal", "value": "2026-01-06"},
                    ]},
                    "operator": "equals",
                    "right": {"kind": "literal", "value": 2},
                }, {}),
                True,
            )


if __name__ == "__main__":
    unittest.main()
