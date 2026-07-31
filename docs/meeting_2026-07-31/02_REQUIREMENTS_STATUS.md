# Requirements Status

The official tracker currently contains 62 requirements and still marks all of them as `Pending`. The table below is the implementation review against the current prototype. These statuses should be validated with stakeholders before updating the official workbook.

## Implemented foundation

| Requirement | Current status | Evidence / qualification |
|---|---|---|
| REQ-026 Exception handling for invalid records | Implemented | Invalid rows are routed to quarantine. |
| REQ-029 Approval and rejection workflow | Implemented | Authorized users can approve/reject with decision history. |
| REQ-033 Draft vs Published states | Implemented | Local runtime and published snapshot are separated. |
| REQ-035 Requester role | Implemented | Requesters submit requests without direct database writes. |
| REQ-038 Auditor role | Implemented | Read-oriented audit access and audit exports exist. |
| REQ-039 Master Admin role | Implemented | Master security and recovery routes are protected. |
| REQ-040 Temporary delegated permissions | Implemented | Scoped, expiring temporary access is audited. |
| REQ-042 Immutable audit logs | Implemented foundation | Append-only audit events exist; retention policy remains open. |
| REQ-043 User/device/timestamp tracking | Implemented foundation | Application actor, workstation and UTC timestamps are recorded. |
| REQ-044 Decision history | Implemented | Approval, rejection, quarantine and publication events are recorded. |
| REQ-045 Data lineage tracking | Implemented foundation | Source, file, checksum, batch, row and field lineage are stored. |
| REQ-047 SLA countdown and aging | Implemented foundation | Due dates and initial overdue escalation are available. |
| REQ-054 Automatic backups | Implemented | Backup is created before controlled publication. |
| REQ-055 Snapshot before publication | Implemented | Runtime snapshots include checksum and manifest. |
| REQ-056 Recovery functionality | Implemented foundation | Master Admin restore flow exists and is audited. |
| REQ-058 SharePoint folder structure | Implemented for development | Simulated and synchronized folder layouts exist; production permissions remain to confirm. |
| REQ-065 Web-based interface | Implemented | Local Flask/Waitress web interface preserves a future migration path. |

## In progress

| Requirement group | Current status | What remains |
|---|---|---|
| REQ-004 Duplicate worker detection | In Progress | Request idempotency exists; worker identity rules need finalization. |
| REQ-008 Mandatory field validation | In Progress | Initial validation exists; official required-field dictionary is pending. |
| REQ-012/013 Central worker profile | In Progress | Worker/Employee ORM exists; not all source systems are connected. |
| REQ-016 Vendor ownership | In Progress | Vendor normalization exists for current files; hierarchy rules need approval. |
| REQ-017 Roster Lock vs Fieldglass | In Progress | Matching foundation exists; formal reconciliation report is pending. |
| REQ-022 Automated Roster Lock ingestion | In Progress | Watcher and adapter work; production folder and submission rules need sign-off. |
| REQ-023 Automated Fieldglass import | In Progress | RSR export is supported; official Fieldglass report mapping is not approved. |
| REQ-024/025/027 File validation, preview and templates | In Progress | Technical foundation exists; official templates and data dictionary are pending. |
| REQ-028/030/031 Review, quarantine and lifecycle states | In Progress | Workflow exists; business state names and decision codes need confirmation. |
| REQ-032/034/057 Single writer, versioning and conflicts | In Progress | Controls exist; multi-workstation and long-running concurrency tests remain. |
| REQ-037 Administrator permissions | In Progress | Admin operations exist; final publication responsibilities need agreement. |
| REQ-041 Dual authentication | In Progress | Application login is active; Windows identity is currently traceability, not AD validation. |
| REQ-046/048/049 SLA and notifications | In Progress | In-app alerts exist; recipients, thresholds and external channels remain open. |
| REQ-050/051 Dashboards | In Progress | Operational overview exists; executive metrics and reporting definitions remain. |
| REQ-061 Salesforce workflow | In Progress | Official workbook generation exists; automated Salesforce profile creation does not. |

## Dependencies and future scope

- REQ-001, REQ-003, REQ-005, REQ-006, REQ-007, REQ-009 and REQ-010: business validations require approved rules and source fields.
- REQ-014, REQ-018, REQ-019 and REQ-021: source precedence and reconciliation require stakeholder decisions and additional sources.
- REQ-011, REQ-052 and REQ-053: milestone, weekly reconciliation and offboarding reports remain unimplemented.
- REQ-060: AD/Azure dependency assessment remains open.
- REQ-062 and REQ-063: CXOne and NICE IEX workflows remain future implementation items.
- REQ-064: SQL Server migration is a future-state option, not an MVP requirement.
- REQ-066: an external workflow orchestrator is future scope.
