"""Compatibility import for the application Rules service.

The implementation lives in :mod:`iam_automation.application.rules.service`.
This module remains so existing routes, integrations and callers do not need
to change during the package reorganization.
"""

from .rules.service import BusinessRuleService

__all__ = ["BusinessRuleService"]
