"""Pure evaluator for the allowlisted business-rule condition language.

This module intentionally depends only on the Python standard library and
domain calendar primitives. It does not know about SQLite, SQLAlchemy, Flask,
source adapters, routes or templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from numbers import Number
from typing import Any

from .calendar import CalendarConfigurationRequired, RuleCalendarSettings, business_days_between


class ConditionValidationError(ValueError):
    """Raised when a condition is malformed or uses an unsupported operation."""


_MISSING = object()
_ISO_DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})")
_US_DATE_RE = re.compile(r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})")


@dataclass(frozen=True)
class EvaluationResult:
    matched: bool
    trace: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class ConditionEvaluator:
    """Evaluate safe, typed-enough conditions against a payload."""

    OPERATORS = frozenset({
        "exists", "missing", "equals", "not_equals", "contains", "in",
        "greater_than", "less_than", "between", "before", "after",
    })
    DERIVED_FUNCTIONS = frozenset({"business_days_between"})

    def __init__(self, calendar: RuleCalendarSettings | None = None):
        self.calendar = calendar

    def evaluate(self, condition: dict[str, Any], payload: dict[str, Any]) -> EvaluationResult:
        if not isinstance(condition, dict):
            raise ConditionValidationError("A rule condition must be an object.")
        if not isinstance(payload, dict):
            raise ConditionValidationError("A rule payload must be an object.")
        trace: list[dict[str, Any]] = []
        matched = self._evaluate_node(condition, payload, trace)
        return EvaluationResult(matched=matched, trace=tuple(trace))

    def matches(self, condition: dict[str, Any], payload: dict[str, Any]) -> bool:
        return self.evaluate(condition, payload).matched

    def validate(self, condition: dict[str, Any]) -> None:
        """Validate the complete condition tree without needing source data."""
        if not isinstance(condition, dict):
            raise ConditionValidationError("A rule condition must be an object.")
        if "all" in condition or "any" in condition:
            key = "all" if "all" in condition else "any"
            for child in self._children(condition, key):
                self.validate(child)
            return
        if "not" in condition:
            child = condition.get("not")
            if not isinstance(child, dict):
                raise ConditionValidationError("'not' must contain one condition object.")
            self.validate(child)
            return
        if "field" in condition:
            if not str(condition.get("field") or "").strip():
                raise ConditionValidationError("A legacy condition requires a field.")
            operator = str(condition.get("operator") or "").casefold()
            if operator not in self.OPERATORS:
                return  # Legacy persisted rules historically treated this as no match.
            if operator in {"between", "in"} and not isinstance(condition.get("value"), (list, tuple)):
                raise ConditionValidationError(f"{operator} requires a list value.")
            return
        if "left" not in condition or "operator" not in condition or "right" not in condition:
            raise ConditionValidationError("A condition requires left, operator and right operands.")
        operator = str(condition.get("operator") or "").casefold()
        if operator not in self.OPERATORS:
            raise ConditionValidationError(f"Unsupported rule operator: {operator or 'empty'}.")
        self._validate_operand(condition["left"])
        self._validate_operand(condition["right"])

    def _validate_operand(self, operand: Any) -> None:
        if not isinstance(operand, dict):
            raise ConditionValidationError("Operands must be objects.")
        kind = str(operand.get("kind") or "").casefold()
        if kind == "literal":
            return
        if kind == "field":
            if not str(operand.get("field") or "").strip():
                raise ConditionValidationError("A field operand requires a field name.")
            return
        if kind == "derived":
            function = str(operand.get("function") or "").casefold()
            if function not in self.DERIVED_FUNCTIONS:
                raise ConditionValidationError(f"Unsupported derived function: {function or 'empty'}.")
            arguments = operand.get("arguments")
            if not isinstance(arguments, list) or len(arguments) != 2:
                raise ConditionValidationError("business_days_between requires two arguments.")
            for argument in arguments:
                self._validate_operand(argument)
            boundary = str(operand.get("date_boundary") or (self.calendar.date_boundary if self.calendar else "")).upper()
            if boundary not in {"EXCLUSIVE_START_INCLUSIVE_END", "INCLUSIVE_BOTH"}:
                if not boundary:
                    return
                raise ConditionValidationError(f"Unsupported date boundary: {boundary}.")
            return
        raise ConditionValidationError(f"Unsupported operand kind: {kind or 'empty'}.")

    def _evaluate_node(self, condition: dict[str, Any], payload: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
        if "all" in condition:
            children = self._children(condition, "all")
            result = all(self._evaluate_node(child, payload, trace) for child in children)
            trace.append({"type": "group", "operator": "all", "matched": result})
            return result
        if "any" in condition:
            children = self._children(condition, "any")
            result = any(self._evaluate_node(child, payload, trace) for child in children)
            trace.append({"type": "group", "operator": "any", "matched": result})
            return result
        if "not" in condition:
            child = condition.get("not")
            if not isinstance(child, dict):
                raise ConditionValidationError("'not' must contain one condition object.")
            result = not self._evaluate_node(child, payload, trace)
            trace.append({"type": "group", "operator": "not", "matched": result})
            return result

        if "field" in condition:
            field_name = str(condition.get("field") or "").strip()
            if not field_name:
                raise ConditionValidationError("A legacy condition requires a field.")
            actual = payload.get(field_name, _MISSING)
            operator = str(condition.get("operator") or "").casefold()
            expected = condition.get("value")
            result = self._apply(operator, actual, expected, legacy=True)
            trace.append({"type": "comparison", "field": field_name, "operator": operator, "matched": result})
            return result

        if "left" not in condition or "operator" not in condition or "right" not in condition:
            raise ConditionValidationError("A condition requires left, operator and right operands.")
        operator = str(condition.get("operator") or "").casefold()
        if operator not in self.OPERATORS:
            raise ConditionValidationError(f"Unsupported rule operator: {operator or 'empty'}.")
        actual = self._resolve_operand(condition["left"], payload)
        expected = self._resolve_operand(condition["right"], payload)
        result = self._apply(operator, actual, expected)
        trace.append({"type": "comparison", "operator": operator, "matched": result})
        return result

    @staticmethod
    def _children(condition: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
        children = condition.get(key)
        if not isinstance(children, list) or not children:
            raise ConditionValidationError(f"'{key}' must contain a non-empty list of conditions.")
        if not all(isinstance(child, dict) for child in children):
            raise ConditionValidationError(f"Every '{key}' item must be a condition object.")
        return tuple(children)

    def _resolve_operand(self, operand: Any, payload: dict[str, Any]) -> Any:
        if not isinstance(operand, dict):
            raise ConditionValidationError("Operands must be objects.")
        kind = str(operand.get("kind") or "").casefold()
        if kind == "literal":
            return operand.get("value", _MISSING)
        if kind == "field":
            field_name = str(operand.get("field") or "").strip()
            if not field_name:
                raise ConditionValidationError("A field operand requires a field name.")
            source = str(operand.get("source") or "").strip().upper()
            source_payload = payload
            if source:
                sources = payload.get("sources")
                if isinstance(sources, dict) and isinstance(sources.get(source), dict):
                    source_payload = sources[source]
                elif isinstance(payload.get(source), dict):
                    source_payload = payload[source]
                elif field_name in payload:
                    return payload.get(field_name, _MISSING)
                else:
                    return _MISSING
            return source_payload.get(field_name, _MISSING)
        if kind == "derived":
            function = str(operand.get("function") or "").casefold()
            if function not in self.DERIVED_FUNCTIONS:
                raise ConditionValidationError(f"Unsupported derived function: {function or 'empty'}.")
            arguments = operand.get("arguments")
            if not isinstance(arguments, list) or len(arguments) != 2:
                raise ConditionValidationError("business_days_between requires two arguments.")
            start = self._as_date(self._resolve_operand(arguments[0], payload))
            end = self._as_date(self._resolve_operand(arguments[1], payload))
            if start is None or end is None:
                return _MISSING
            if self.calendar is None:
                raise CalendarConfigurationRequired(
                    "A rule calendar is required. Ask an administrator to configure and activate the calendar before evaluating this rule."
                )
            boundary = str(operand.get("date_boundary") or self.calendar.date_boundary).upper()
            if boundary not in {"EXCLUSIVE_START_INCLUSIVE_END", "INCLUSIVE_BOTH"}:
                raise ConditionValidationError(f"Unsupported date boundary: {boundary}.")
            return business_days_between(
                start,
                end,
                self.calendar.holidays_between(start, end),
                operating_weekdays=self.calendar.operating_weekdays,
                start_inclusive=boundary == "INCLUSIVE_BOTH",
            )
        raise ConditionValidationError(f"Unsupported operand kind: {kind or 'empty'}.")

    @classmethod
    def _apply(cls, operator: str, actual: Any, expected: Any, *, legacy: bool = False) -> bool:
        if operator not in cls.OPERATORS:
            if legacy:
                return False
            raise ConditionValidationError(f"Unsupported rule operator: {operator or 'empty'}.")
        if operator == "exists":
            return actual is not _MISSING
        if operator == "missing":
            return actual is _MISSING or actual is None or actual == ""
        if actual is _MISSING:
            return False
        if operator == "equals":
            return cls._compare(actual, expected) == 0
        if operator == "not_equals":
            return cls._compare(actual, expected) != 0
        if operator == "contains":
            if isinstance(actual, (list, tuple, set, frozenset)):
                return expected in actual
            return str(expected or "").casefold() in str(actual or "").casefold()
        if operator == "in":
            if not isinstance(expected, (list, tuple, set, frozenset)):
                return False
            return any(cls._compare(actual, item) == 0 for item in expected)
        if operator == "greater_than":
            return cls._compare(actual, expected) > 0
        if operator == "less_than":
            return cls._compare(actual, expected) < 0
        if operator == "between":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                if legacy:
                    return False
                raise ConditionValidationError("between requires two boundary values.")
            return cls._compare(actual, expected[0]) >= 0 and cls._compare(actual, expected[1]) <= 0
        if operator == "before":
            comparison = cls._compare_dates(actual, expected)
            return comparison is not None and comparison < 0
        if operator == "after":
            comparison = cls._compare_dates(actual, expected)
            return comparison is not None and comparison > 0
        return False

    @classmethod
    def _compare(cls, actual: Any, expected: Any) -> int:
        actual_date = cls._as_date(actual)
        expected_date = cls._as_date(expected)
        if actual_date is not None and expected_date is not None:
            return (actual_date > expected_date) - (actual_date < expected_date)
        left = cls._typed_value(actual)
        right = cls._typed_value(expected)
        if type(left) is type(right) or isinstance(left, Number) and isinstance(right, Number):
            return (left > right) - (left < right)
        left_text, right_text = str(left).casefold(), str(right).casefold()
        return (left_text > right_text) - (left_text < right_text)

    @classmethod
    def _compare_dates(cls, actual: Any, expected: Any) -> int | None:
        left = cls._as_date(actual)
        right = cls._as_date(expected)
        if left is None or right is None:
            return None
        return (left > right) - (left < right)

    @staticmethod
    def _typed_value(value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.casefold() in {"true", "false"}:
                return text.casefold() == "true"
            try:
                return float(text) if "." in text else int(text)
            except ValueError:
                return text
        return value

    @staticmethod
    def _as_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        for pattern in (_ISO_DATE_RE, _US_DATE_RE):
            match = pattern.match(text)
            if not match:
                continue
            try:
                return date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            except ValueError:
                return None
        return None


__all__ = ["ConditionEvaluator", "ConditionValidationError", "EvaluationResult"]
