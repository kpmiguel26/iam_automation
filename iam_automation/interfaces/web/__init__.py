"""
File: iam_automation/interfaces/web/__init__.py
Purpose: Loopback-only Flask web interface.
Responsibilities: Exposes or coordinates: __getattr__.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

__all__ = ["LocalWebAppServer", "create_app", "launch_local_webapp", "launch_local_webapp_process"]


def __getattr__(name: str):
    if name in __all__:
        from ... import webapp
        return getattr(webapp, name)
    raise AttributeError(name)
#endfile
