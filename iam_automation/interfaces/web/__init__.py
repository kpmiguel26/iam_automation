"""
File: iam_automation/interfaces/web/__init__.py
Purpose: Loopback-only Flask web interface.
Responsibilities: Exposes or coordinates: __getattr__.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

__all__ = ["LocalWebAppServer", "create_app", "launch_local_webapp", "launch_local_webapp_process"]


def __getattr__(name: str):
    if name in __all__:
        from ... import webapp
        return getattr(webapp, name)
    raise AttributeError(name)
