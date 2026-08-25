"""
File: iam_automation/change_management/__init__.py
Purpose: Request-driven create, update, deactivate, review, and apply workflows.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: change_request
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from ..change_request import ChangeRequest, import_pending_requests, new_request, submit_request

__all__ = ["ChangeRequest", "import_pending_requests", "new_request", "submit_request"]
#endfile
