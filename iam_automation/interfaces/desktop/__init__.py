"""
File: iam_automation/interfaces/desktop/__init__.py
Purpose: PySide6 desktop startup shell.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: qt_startup
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from ...qt_startup import StartupWindow, run_desktop_app

__all__ = ["StartupWindow", "run_desktop_app"]
