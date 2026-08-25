"""
File: iam_automation/security/__init__.py
Purpose: User identity and authorization boundaries.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: identity
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
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
#endfile
