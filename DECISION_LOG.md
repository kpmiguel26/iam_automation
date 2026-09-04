# Decision Log

## 2026-07-17: Reject Centralized Coordinator Assumption

Status: Accepted

The actual infrastructure has no server, central API, service host, persistent VM, or database engine. The previous coordinator-style architecture is archived under `docs/archive/rejected-architecture`.

## 2026-07-17: Use Single-Writer Approval Workflow

Status: Accepted

Ordinary users submit immutable JSON request files. Only Administrator/Writer roles import, review, approve, apply, and publish versioned Access snapshots.

## 2026-07-17: Require Python 3.10 Compatibility

Status: Accepted

The POC must run on Python 3.10+. Dependencies and syntax must remain compatible with Python 3.10.

## 2026-07-22: Add Local Startup Preflight MVC

Status: Accepted

The application starts with a local PySide6 preflight shell. It discovers or accepts a manually selected local OneDrive-synchronized SharePoint folder, validates the Access snapshot and required folders, persists local settings, and only then validates the Windows user. A loopback-only Flask webapp is started after the hard gate succeeds. This does not introduce a central API, persistent service, or shared database server.

Open items from the touchpoint meeting remain pending: the final role matrix, rehire and restricted-user rules, quarantine business rules, and external SharePoint application authentication.
