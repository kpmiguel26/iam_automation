"""
File: iam_automation/interfaces/desktop/__init__.py
Purpose: PySide6 desktop startup shell.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: qt_startup
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from ...qt_startup import StartupWindow, run_desktop_app

__all__ = ["StartupWindow", "run_desktop_app"]
#endfile
