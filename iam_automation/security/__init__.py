"""
File: iam_automation/security/__init__.py
Purpose: User identity and authorization boundaries.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: identity
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from ..identity import (
    CurrentUser,
    ROLE_ADMINISTRATOR,
    ROLE_AUDITOR,
    ROLE_REQUESTER,
    ROLE_REVIEWER,
    ROLE_WRITER,
    validate_current_user,
)

__all__ = [
    "CurrentUser",
    "ROLE_ADMINISTRATOR",
    "ROLE_AUDITOR",
    "ROLE_REQUESTER",
    "ROLE_REVIEWER",
    "ROLE_WRITER",
    "validate_current_user",
]
