# Decision Log

## 2026-07-17: Reject Centralized Coordinator Assumption

Status: Accepted

The actual infrastructure has no server, central API, service host, persistent VM, or database engine. The previous coordinator-style architecture is archived under `docs/rejected_architecture`.

## 2026-07-17: Use Single-Writer Approval Workflow

Status: Accepted

Ordinary users submit immutable JSON request files. Only Administrator/Writer roles import, review, approve, apply, and publish versioned Access snapshots.

## 2026-07-17: Require Python 3.10 Compatibility

Status: Accepted

The POC must run on Python 3.10+. Dependencies and syntax must remain compatible with Python 3.10.
