"""
File: iam_automation/environment/__init__.py
Purpose: Environment discovery and startup preflight use cases.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: sharepoint_discovery, startup
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from ..sharepoint_discovery import DiscoveryCandidate, discover_candidates
from ..startup import PreflightResult, StartupController, StartupSettings, StartupState

__all__ = [
    "DiscoveryCandidate",
    "PreflightResult",
    "StartupController",
    "StartupSettings",
    "StartupState",
    "discover_candidates",
]
#endfile
