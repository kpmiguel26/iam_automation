# Deferred Scenarios — Phase 2 Writer / Change Management

These scenarios remain documented because the repository contains related code and earlier design work. They are **not Phase 1 UAT requirements** and must not block Phase 1 sign-off.

## Boundary

Phase 1 detects, explains, and exports evidence. Phase 2 writer capabilities would allow an authorized human/process to decide and execute authoritative changes in source platforms. Any future implementation must be separately approved, secured, audited, and tested.

| Deferred scenario / source UAT ID | Deferred capability | Why it is not Phase 1 | Future acceptance focus |
|---|---|---|---|
| UAT-012 extension | Rehire approval or reuse/new Worker decision | Phase 1 detects potential rehire evidence; it does not decide whether to rehire or execute it. | Decision authority, source-of-truth action, separation of duties, audit, rollback. |
| UAT-013 enforcement | No-hire block/reject/override | Phase 1 may classify a policy-relevant finding; it must not block or approve hiring. | Authoritative policy source, override authority, evidence, source-system action. |
| UAT-014 remediation | Correcting a missing source record | Phase 1 reports source absence; it does not alter Fieldglass, AccessNow, Roster, or other sources. | Remediation workflow, owner, authorization, source write audit. |
| UAT-021 | Role/access change, provisioning, deprovisioning, ITSM | These are authoritative lifecycle/access actions. | Approval workflow, connector safety, rollback, downstream confirmation. |
| UAT-031 | Duplicate merge execution | Phase 1 presents candidate identities and evidence; an authoritative merge is a business decision. | Merge authority, reversibility, referential integrity, evidence preservation. |
| UAT-033 live path | Salesforce API create/update | Current Phase 1 output is a manual evidence/handoff export. | API authentication, field mapping, idempotency, downstream ownership. |
| UAT-034 | AD/Azure, CXOne, NICE, SQL, orchestrator, ITSM connectors | These are future integrations and are not required for current reconciliation acceptance. | Connector contract, environment, failure handling, security, support ownership. |
| UAT-048 equivalent | Request approval/apply/publication workflow | Internal request state machines and approvals are change-management behavior. | State machine, separation of duties, approval evidence, authoritative action boundary. |

## Required future gate

Before any deferred capability is enabled, create a new phase-specific scope decision and confirm that Phase 1 cannot reach the writer path accidentally. The technical snapshot publication used to distribute the read-only analytical database is separate and remains a `PHASE1_PLATFORM` capability.
