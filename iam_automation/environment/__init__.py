"""
File: iam_automation/environment/__init__.py
Purpose: Environment discovery and startup preflight use cases.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: sharepoint_discovery, startup
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
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
