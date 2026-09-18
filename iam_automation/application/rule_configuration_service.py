"""Compatibility import for the Rules configuration service."""

from .holiday_provider import fetch_public_holidays
from .rules.configuration import RuleConfigurationService

__all__ = ["RuleConfigurationService", "fetch_public_holidays"]
