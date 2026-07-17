# ADR-001: Use Single-Writer Approval Workflow with Immutable Change Requests

## Context

IAM Automation must run on separately installed Windows workstation applications. The organization does not currently have a server, VM, central API, Windows Service host, or transactional database engine.

## Constraints

Access is the current master data store. SharePoint and OneDrive are available but must not be treated as a transactional database server.

## Decision

Use a single-writer approval workflow. Requesters submit immutable JSON files. An Administrator/Writer imports, reviews, approves, applies, audits, and publishes versioned Access snapshots.

## Alternatives Considered

- Direct multi-user Access editing through OneDrive: rejected due to corruption and conflict risk.
- SQLite stored in OneDrive: rejected because sync-file risks remain.
- Client-side distributed lock file as sole coordination: rejected because no central lock authority exists.
- Imaginary centralized coordinator without infrastructure: rejected because no host exists.
- Full database replacement by every client: rejected because it causes competing master versions.

## Reasons

The design separates submission, review, approval, execution, audit, and publication while fitting the actual infrastructure.

## Risks

Multiple admins can still process batches simultaneously if operational controls fail. OneDrive sync delay can still delay request visibility.

## Mitigations

Restrict writer permissions, use advisory writer markers, compare versions and checksums before publish, keep batch journals, and use idempotent `request_id` processing.

## Consequences

The system prioritizes safety and auditability over immediate direct writes. Request processing is batch-oriented.

## Operational Requirements

Admins must work from a local workspace outside OneDrive, close Access before publication, and follow writer handoff rules.

## Redesign Triggers

Availability of SQL Server, PostgreSQL, a managed database, central API hosting, or Entra-backed workflow automation should trigger redesign.
