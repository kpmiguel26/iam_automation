from __future__ import annotations

import unittest
from datetime import date

from iam_automation.domain.rules.calendar import CalendarConfigurationRequired, RuleCalendarSettings
from iam_automation.domain.rules.evaluator import ConditionEvaluator, ConditionValidationError


class DomainRuleEvaluatorTests(unittest.TestCase):
    def test_simple_field_literal_and_field_field_comparisons(self):
        evaluator = ConditionEvaluator()

        self.assertTrue(evaluator.matches({
            "left": {"kind": "field", "field": "status"},
            "operator": "equals",
            "right": {"kind": "literal", "value": "TERMINATED"},
        }, {"status": "TERMINATED"}))
        self.assertTrue(evaluator.matches({
            "left": {"kind": "field", "field": "termination_date"},
            "operator": "equals",
            "right": {"kind": "field", "field": "effective_date"},
        }, {"termination_date": "2026-09-18", "effective_date": "2026-09-18"}))

    def test_all_any_and_not_preserve_trace(self):
        condition = {
            "all": [
                {"field": "status", "operator": "equals", "value": "ACTIVE"},
                {"not": {"field": "email", "operator": "missing"}},
                {"any": [
                    {"field": "region", "operator": "equals", "value": "WEST"},
                    {"field": "region", "operator": "equals", "value": "PACIFIC"},
                ]},
            ]
        }

        result = ConditionEvaluator().evaluate(condition, {
            "status": "ACTIVE", "email": "user@example.com", "region": "PACIFIC",
        })

        self.assertTrue(result.matched)
        self.assertEqual({"all", "any", "not"}, {
            item["operator"] for item in result.trace if item["type"] == "group"
        })

    def test_derived_business_days_uses_calendar_holidays(self):
        calendar = RuleCalendarSettings(
            timezone="UTC",
            date_boundary="EXCLUSIVE_START_INCLUSIVE_END",
            operating_weekdays=frozenset({0, 1, 2, 3, 4}),
            holiday_dates=frozenset({date(2026, 1, 2)}),
            recurring_holidays=frozenset(),
        )
        condition = {
            "left": {"kind": "derived", "function": "business_days_between", "arguments": [
                {"kind": "literal", "value": "2026-01-01"},
                {"kind": "literal", "value": "2026-01-06"},
            ]},
            "operator": "equals",
            "right": {"kind": "literal", "value": 2},
        }

        self.assertTrue(ConditionEvaluator(calendar).matches(condition, {}))

    def test_malformed_condition_and_unsupported_operator_are_rejected(self):
        evaluator = ConditionEvaluator()

        with self.assertRaises(ConditionValidationError):
            evaluator.validate({"left": {"kind": "field", "field": "status"}, "operator": "sql", "right": {"kind": "literal", "value": "x"}})
        with self.assertRaises(ConditionValidationError):
            evaluator.validate({"all": []})

    def test_derived_evaluation_requires_explicit_calendar_context(self):
        condition = {
            "left": {"kind": "derived", "function": "business_days_between", "arguments": [
                {"kind": "literal", "value": "2026-01-01"},
                {"kind": "literal", "value": "2026-01-06"},
            ]},
            "operator": "equals",
            "right": {"kind": "literal", "value": 3},
        }

        with self.assertRaises(CalendarConfigurationRequired):
            ConditionEvaluator().matches(condition, {})


if __name__ == "__main__":
    unittest.main()
