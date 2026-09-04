# Approval Workflow

1. Admin imports pending requests.
2. Malformed requests are quarantined.
3. Duplicate `request_id` values are rejected.
4. Reviewer validates business context.
5. Admin approves or rejects.
6. Approved requests are checked against current record versions.
7. Conflicting requests are marked `CONFLICT`.
8. Approved non-conflicting requests are applied.
9. Audit events are generated.

Segregation of duties can require that requesters do not approve their own requests.
