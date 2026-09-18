# Deprecated rehire alert service

Status: retired from runtime on 2026-09-18.

`RehireAlertService` was the previous code-owned path for detecting a possible
30-business-day rehire between AccessNow and Roster Lock. It also exposed
employee-route alerts, watcher notifications and an archive action.

That path is no longer executed. The configurable Business Rules engine is now
the only runtime mechanism for advisory findings. A user can create, preview,
activate and disable the required rule from **Administration → Business
rules**, with the calendar and condition decisions stored in versioned SQLite
configuration.

The retired behavior must not be reintroduced as an implicit fallback. If a
future rehire policy is needed, model it as a user-owned rule with explicit
fields, sources, operands, calendar version, severity and evidence
requirements.

The original implementation remains available in repository history for
forensic reference; it is intentionally not imported by application services,
the file watcher, notifications or employee routes.
