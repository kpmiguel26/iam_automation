# Future Migration Strategy

When infrastructure becomes available, move transactional data and workflow state to a real database and service layer.

Future options:

- SQL Server or PostgreSQL.
- Central API.
- Entra ID integration.
- Workflow engine.
- SharePoint retained for documents, templates, and published exports.

Migration should preserve request IDs, batch IDs, audit IDs, database version manifests, and employee record versions.
