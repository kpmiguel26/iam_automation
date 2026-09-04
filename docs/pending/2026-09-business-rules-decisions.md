# Pending Decisions — Business Rules and Alerts

**Owner:** Product, IAM Data Governance and IAM Lifecycle stakeholders  
**Source:** [UAT decision agenda](../uat/UAT_NEXT_MEETING_DECISIONS.md)

These items must remain `Pending` until an owner records the decision, date,
scope and affected UAT scenarios.

| ID | Decision | Current implementation assumption | Effect |
|---|---|---|---|
| P-001 | Rehire calendar and boundaries | Code currently uses inclusive 0–30 business-day logic and optional environment holidays | BR-002, UAT-011/012 |
| P-002 | No-rehire source and matching key | No complete enforcement exists | BR-003, compliance risk |
| P-003 | Protected/master/modifiable fields by source | Meeting gives examples only | BR-004 and import behavior |
| P-004 | Rule configuration authority | Admin CRUD is requested but current release is read-only | Security and scope gate |
| P-005 | Alert severity, recipients and retention | Existing alerts are not a complete severity matrix | AL-003/AL-004 and operations |
| P-006 | Resolution evidence and disposition vocabulary | Review/audit structures exist but minimum evidence is incomplete | Findings and UAT acceptance |
| P-007 | Rule effective dating and version migration | Not defined | Reproducibility and audit |

No implementation should silently convert these assumptions into approved
business policy. Link the final decision from this document and update the
feature status registry.
