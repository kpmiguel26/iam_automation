# Future Migration Strategy

## Current SQLite migration strategy

The local runtime database is managed with SQLAlchemy ORM and Alembic. The
preflight bootstrap creates the baseline SQLite schema and upgrades it to the
current Alembic head before the webapp starts. Existing databases created by
the original migration runner are stamped to the equivalent Alembic revision;
their data is not replaced.

Migration files live under `iam_automation/database/alembic/versions/` and are
the only place where future schema changes should be added. SQLite changes
that require table alteration must use Alembic batch operations and include a
data-preserving test. A development database must never be copied over a
data-bearing workspace database merely to apply a schema change.

Alembic is a schema migration tool, not a concurrency solution. Each
workstation continues to use its own local SQLite copy, while JSON requests
and bug reports remain the shared SharePoint workflow layer.

When infrastructure becomes available, move transactional data and workflow state to a real database and service layer.

Future options:

- SQL Server or PostgreSQL.
- Central API.
- Entra ID integration.
- Workflow engine.
- SharePoint retained for documents, templates, and published exports.

Migration should preserve request IDs, batch IDs, audit IDs, database version manifests, and employee record versions.
