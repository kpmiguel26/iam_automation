# Working Decisions

## DEC-2026-07-23-01: ORM Boundary

Runtime SQLite business data is accessed through SQLAlchemy ORM models and repositories. The existing schema bootstrap remains a migration-compatible infrastructure boundary and is not used by web controllers for business operations.

## DEC-2026-07-23-02: Separated Views

Flask controllers must not contain large HTML documents. Jinja templates belong under `iam_automation/templates/`; shared and brand-specific styles belong under `iam_automation/static/`.

## DEC-2026-07-23-03: Local Bootstrap Assets

Bootstrap 5.3.3 is vendored into the repository. The application does not require a CDN connection to render the local login, dashboard or administration pages.

## DEC-2026-07-23-04: Local Runtime Database

The web application works against the validated local runtime SQLite copy. It does not write directly to the published Access database. Publication and synchronization remain explicit controlled operations.

## DEC-2026-07-23-05: Feature Branch Discipline

The current feature is developed on `feature/admin-control-center`. Future work must use `feature/<name>`, `fix/<name>` or `chore/<name>` branches and must not be developed directly on `main`.

## DEC-2026-07-23-06: Identity Discovery Queue

An identity discovered on a workstation is not automatically a published approval in strict mode. The workstation writes a deduplicated request to `database/snapshots/iam_identity_discovery.json` with `PENDING` status. The admin reads the synchronized JSON on startup, reviews the identity and assigns human-readable roles through controlled selectors. Development mode may auto-approve for testing; strict mode blocks the identity until administrative approval.
