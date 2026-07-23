"""Loopback-only Flask web interface."""

__all__ = ["LocalWebAppServer", "create_app", "launch_local_webapp", "launch_local_webapp_process"]


def __getattr__(name: str):
    if name in __all__:
        from ... import webapp
        return getattr(webapp, name)
    raise AttributeError(name)
